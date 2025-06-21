import dataclasses
import json
import os
import re
import sys
import time

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Union

import discord
import pytz

from discord.ext import commands

root_dir = Path(os.path.dirname(os.path.realpath(__file__)))

ZC_GUILD_ID = 876899628556091432
CHANNELS_TO_SUMMARIZE = {
    # Top bugs.
    1021382849603051571: 1286523088900591699,
    # Top feature requests.
    1021385902708248637: 1286512335829336146,
}
DRY_RUN = False


@dataclass
class Tag:
    name: str
    emoji: str


@dataclass
class Issue:
    id: int
    name: str
    status: Union['open', 'closed', 'pending', 'unknown']
    url: str
    votes: int
    tags: List[Tag]
    message_count: int

    def get_tag_str(self):
        return ' '.join(
            str(t.emoji) for t in self.tags if t.emoji and not isinstance(t.emoji, str)
        )

    def has_tag(self, name: str):
        return next((t for t in self.tags if t.name == name), None) != None


def json_encode_value(x):
    if dataclasses.is_dataclass(x):
        return dataclasses.asdict(x)
    return x


def create_bot():
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    return commands.Bot('.', intents=intents)


bot = create_bot()


async def get_all_threads(channel: discord.ForumChannel):
    threads = []
    threads.extend(channel.threads)
    async for thread in channel.archived_threads(limit=None):
        threads.append(thread)
    return threads


def is_upvote_reaction(reaction: discord.Reaction):
    if isinstance(reaction.emoji, str):
        return False

    return reaction.emoji in ['this', 'heart', 'thumbsup']


async def get_issues_from_channel(
    bot: commands.Bot, channel: discord.ForumChannel, summary_thread_id: int
):
    issues: List[Issue] = []
    for thread in await get_all_threads(channel):
        if thread.id == summary_thread_id or thread.parent_id == summary_thread_id:
            continue
        if thread.name == 'Top Bug Reports' or thread.name == 'Top Feature Requests':
            continue

        closed_tag_names = [
            'Already Exists',
            'Closed',
            'Denied',
            'Fixed',
            'Stale',
        ]
        is_open = next((t for t in thread.applied_tags if t.name == 'Open'), None)
        is_closed = next(
            (t for t in thread.applied_tags if t.name in closed_tag_names), None
        )
        dev_disc = next(
            (t for t in thread.applied_tags if t.name == 'DevDiscussion'), None
        )

        if dev_disc and not is_open:
            continue

        status = 'unknown'
        if is_closed and not is_open:
            status = 'closed'
        elif is_open and not is_closed:
            status = 'open'
        elif not is_open and not is_closed:
            status = 'pending'

        message = [x async for x in thread.history(oldest_first=True, limit=1)][0]
        this_reaction = next(
            (r for r in message.reactions if is_upvote_reaction(r)), None
        )
        votes = this_reaction.count if this_reaction else 0

        issues.append(
            Issue(
                id=thread.id,
                name=thread.name,
                status=status,
                url=thread.jump_url,
                votes=votes,
                tags=[Tag(tag.name, tag.emoji.name) for tag in thread.applied_tags],
                message_count=thread.message_count,
            )
        )
        # if len(issues) > 25:
        #     break

    return issues


def split_message_content(content: str):
    # https://stackoverflow.com/a/72943629/2788187
    start_idx = 0
    length = 1999
    end_idx = 0
    chunks = []
    while end_idx < len(content):
        end_idx = content.rfind("\n", start_idx, length + start_idx) + 1
        chunks.append(content[start_idx:end_idx])
        start_idx = end_idx
    return chunks


def format_issue(issue: Issue, this_emoji) -> str:
    return f'`{str(issue.votes).rjust(2, " ")}` {this_emoji} [{issue.name}]({issue.url}) {issue.get_tag_str()}'


def create_section(label: str, issues: List[Issue], this_emoji) -> str:
    content = f'# {label} ({len(issues)})\n'
    for issue in issues:
        content += format_issue(issue, this_emoji)
        content += '\n'
    if not issues:
        return 'None\n'
    return content


async def process_channel(bot: commands.Bot, channel_id: int, summary_thread_id: int):
    guild = bot.get_guild(ZC_GUILD_ID)
    channel = guild.get_channel(channel_id)
    # await channel.create_thread(name='Top Bug Reports', content='Top Bug Reports')
    # sys.exit(1)
    summary_thread = channel.get_thread(summary_thread_id)
    this_emoji = guild.get_emoji(877358416992030731)

    print('collecting issues')

    issues: List[Issue] = []
    for thread in await get_issues_from_channel(bot, channel, summary_thread):
        issues.append(thread)
    issues = sorted(issues, key=lambda issue: -issue.votes)

    open_issues = []
    pending_issues = []
    unknown_issues = []
    highprio_issues = []
    lowprio_issues = []
    for issue in issues:
        if issue.status == 'pending':
            pending_issues.append(issue)
        elif issue.status == 'unknown':
            unknown_issues.append(issue)
        elif issue.status == 'open':
            if issue.has_tag('High Priority'):
                highprio_issues.append(issue)
            elif issue.has_tag('Low Priority'):
                lowprio_issues.append(issue)
            else:
                open_issues.append(issue)
                issue.tags = [
                    t for t in issue.tags if t.name != 'Open' and t.name != 'Unassigned'
                ]

    content = ''

    digest = process_digest(channel_id, issues, this_emoji)
    if digest:
        content += f'{digest}\n'

    if pending_issues:
        content += create_section('Pending', pending_issues, this_emoji)
    if highprio_issues:
        content += create_section('Open - High Priority', highprio_issues, this_emoji)
    content += create_section('Open', open_issues, this_emoji)
    if lowprio_issues:
        content += create_section('Open - Low Priority', lowprio_issues, this_emoji)
    if unknown_issues:
        content += create_section('Unknown', unknown_issues, this_emoji)

    # TODO
    # content += f'# Fixed in the last month ({len(pending_issues)})\n'

    print(content)
    if DRY_RUN:
        return

    chunks = split_message_content(content)
    print(f'update content: {len(chunks)} messages needed')

    existing_messages = [
        x
        async for x in summary_thread.history(oldest_first=True, limit=None)
        if not x.is_system()
    ]
    first_message = existing_messages[0]
    existing_messages = existing_messages[1:]

    # Legend.
    content = ''
    for i, tag in enumerate(channel.available_tags):
        content += f'{tag.emoji}  {tag.name}\n'
    await first_message.edit(content=content)

    for i, chunk in enumerate(chunks):
        if i >= len(existing_messages):
            await summary_thread.send(content=chunk)
        else:
            await existing_messages[i].edit(content=chunk)
    for m in existing_messages[len(chunks) :]:
        await m.delete()

    print(f'done updating content')


def load_last_run(channel_id: int):
    path = Path(f'./last_run/{channel_id}.json')
    if path.exists():
        last_run_json = json.loads(path.read_text('utf-8'))
        last_run_json['issues'] = [Issue(**issue) for issue in last_run_json['issues']]
        return last_run_json

    return None


def save_run(channel_id: int, issues: List[Issue]):
    path = Path(f'./last_run/{channel_id}.json')
    path.parent.mkdir(exist_ok=True)
    data = {
        'time': time.time(),
        'issues': issues,
    }
    j = json.dumps(data, default=json_encode_value, indent=2)
    path.write_text(j)


def process_digest(channel_id: int, issues: List[Issue], this_emoji):
    last_run = load_last_run(channel_id)
    if last_run == None:
        print('No last run, will process digest next time')
        save_run(channel_id, issues)
        return None

    print('processing digest')

    last_issue_by_id = {}
    for issue in last_run['issues']:
        last_issue_by_id[issue.id] = issue

    last_time_str = datetime.fromtimestamp(
        last_run['time'], pytz.timezone("US/Pacific")
    ).strftime('%Y-%m-%d %H:%M %Z')
    lines = [f'# Digest (activity since {last_time_str})']

    for issue in issues:
        last_issue = last_issue_by_id.get(issue.id)
        activities = []

        if not last_issue:
            activities.append('NEW')
        elif issue.status == 'closed' and last_issue.status != 'closed':
            activities.append('CLOSED')

        last_issue_message_count = last_issue.message_count if last_issue else 0
        if last_issue_message_count < issue.message_count:
            new_comments = issue.message_count - last_issue_message_count
            activities.append(f'+{new_comments} COMMENTS')

        if activities:
            activity = ', '.join(activities)
            lines.append(f'{format_issue(issue, this_emoji)} ({activity})')

    if len(lines) == 1:
        lines.append('none')

    # Update the last run every 3 days.
    MS_PER_HOUR = 3600000
    MS_PER_DAY = 86400000
    DIGEST_DURATION = 3 * MS_PER_DAY
    # Give some lee-way since the cron won't always finish at the same time.
    if time.time() - last_run['time'] > MS_PER_DAY - MS_PER_HOUR:
        save_run(channel_id, issues)

    print('finished digest')
    return '\n'.join(lines)


@bot.event
async def on_ready():
    print('starting')
    if DRY_RUN:
        print('DRY RUN!')

    for channel_id, summary_thread_id in CHANNELS_TO_SUMMARIZE.items():
        print(f'processing channel {channel_id}')
        await process_channel(bot, channel_id, summary_thread_id)

    print('done')
    await bot.close()


bot.run(sys.argv[1])

import dataclasses
import json
import logging
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

root_dir = Path(os.path.dirname(os.path.realpath(__file__)))

ZC_GUILD_ID = 876899628556091432
CHANNELS_TO_SUMMARIZE = {
    # Top bugs.
    1021382849603051571: 1286523088900591699,
    # Top feature requests.
    1021385902708248637: 1286512335829336146,
}
# Map channel IDs to human readable names for the summary.
CHANNEL_ID_TO_NAME = {
    1021382849603051571: 'bugs',
    1021385902708248637: 'features',
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


@dataclass
class Snapshot:
    time: float
    issues: List[Issue]


def json_encode_value(x):
    if isinstance(x, Snapshot):
        return {'time': x.time, 'issues': x.issues}
    if isinstance(x, Issue):
        return {
            'id': x.id,
            'name': x.name,
            'status': x.status,
            'url': x.url,
            'votes': x.votes,
            'tags': x.tags,
            'message_count': x.message_count,
        }
    if isinstance(x, Tag):
        return {'name': x.name, 'emoji': x.emoji}
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
    archived_limit = 10 if DRY_RUN else None
    async for thread in channel.archived_threads(limit=archived_limit):
        threads.append(thread)
    return threads


def is_upvote_reaction(reaction: discord.Reaction):
    if isinstance(reaction.emoji, str):
        return False

    return reaction.emoji.name in ['this', 'heart', 'thumbsup']


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

        if DRY_RUN and len(issues) >= 5:
            break

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

    logger.info('collecting issues')

    issues: List[Issue] = []
    for thread in await get_issues_from_channel(bot, channel, summary_thread):
        issues.append(thread)
    issues = sorted(issues, key=lambda issue: -issue.votes)

    open_issues = []
    blocker_issues = []
    pending_issues = []
    unknown_issues = []
    highprio_issues = []
    lowprio_issues = []
    for issue in issues:
        if issue.has_tag('Blocker'):
            blocker_issues.append(issue)
        elif issue.status == 'pending':
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

    content = ''

    content += f'[Dashboard](https://zquestclassic.github.io/discord-scripts/dashboard/?channel={CHANNEL_ID_TO_NAME[channel_id]}&mode=status)\n\n'

    digest = process_digest(channel_id, issues, this_emoji)
    # if digest:
    #     content += f'{digest}\n'

    if blocker_issues:
        content += create_section('Blockers', blocker_issues, this_emoji)
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
        return issues

    chunks = split_message_content(content)
    logger.info(f'update content: {len(chunks)} messages needed')

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

    logger.info(f'done updating content')
    return issues


SEC_PER_HOUR = 3600
SEC_PER_DAY = 86400
# TODO: change to 3 days, for now it doesn't really matter i guess.
DIGEST_DURATION = 9999 * SEC_PER_DAY


def load_snapshots(channel_id: int) -> List[Snapshot]:
    path = Path(f'./snapshots/{channel_id}.json')
    if path.exists():
        snapshots_json = json.loads(path.read_text('utf-8'))
        snapshots = []
        for s in snapshots_json:
            issues = []
            for i in s.get('issues', []):
                tags = [Tag(**t) for t in i.get('tags', [])]
                i_copy = dict(i)
                i_copy['tags'] = tags
                issues.append(Issue(**i_copy))
            snapshots.append(Snapshot(time=s['time'], issues=issues))
        return snapshots

    return []


def save_snapshots(
    existing_snapshots: List[Snapshot], channel_id: int, issues: List[Issue]
):
    path = Path(f'./snapshots/{channel_id}.json')
    path.parent.mkdir(exist_ok=True)
    now = time.time()
    snapshot = Snapshot(now, issues)
    existing_snapshots.append(snapshot)
    existing_snapshots = [
        s for s in existing_snapshots if now - s.time < DIGEST_DURATION * 1.1
    ]
    j = json.dumps(existing_snapshots, default=json_encode_value, indent=2)
    path.write_text(j, 'utf-8')


def process_digest(channel_id: int, issues: List[Issue], this_emoji):
    snapshots = load_snapshots(channel_id)
    if not snapshots:
        logger.warn('No snapshot, will process digest next time')
        save_snapshots(snapshots, channel_id, issues)
        return None

    logger.info('processing digest')

    # Find snapshot closest to target start time.
    now = time.time()
    snapshot = min(snapshots, key=lambda s: abs(now - s.time - DIGEST_DURATION))

    last_issue_by_id = {}
    for issue in snapshot.issues:
        last_issue_by_id[issue.id] = issue

    last_time_str = datetime.fromtimestamp(
        snapshot.time, pytz.timezone("US/Pacific")
    ).strftime('%Y-%m-%d %H:%M %Z')
    lines = [f'# Digest (activity since {last_time_str})']

    new_section = []
    closed_section = []
    other_section = []

    for issue in issues:
        last_issue = last_issue_by_id.get(issue.id)

        last_issue_message_count = last_issue.message_count if last_issue else 0
        new_comments = 0
        if last_issue_message_count < issue.message_count:
            new_comments = issue.message_count - last_issue_message_count

        if not last_issue:
            new_section.append((issue, new_comments))
        elif issue.status == 'closed' and last_issue.status != 'closed':
            closed_section.append((issue, new_comments))
        elif new_comments:
            other_section.append((issue, new_comments))

    if new_section:
        lines.append(f'__new__ ({len(new_section)})\n')
        for issue, new_comments in new_section:
            suffix = f' (+{new_comments} COMMENTS)' if new_comments else ''
            lines.append(f'{format_issue(issue, this_emoji)}{suffix}')
        lines.append('')

    if closed_section:
        lines.append(f'__closed__ ({len(closed_section)})\n')
        for issue, new_comments in closed_section:
            suffix = f' (+{new_comments} COMMENTS)' if new_comments else ''
            lines.append(f'{format_issue(issue, this_emoji)}{suffix}')
        lines.append('')

    if other_section:
        lines.append(f'__comments__ ({len(other_section)})\n')
        for issue, new_comments in other_section:
            suffix = f' (+{new_comments} COMMENTS)' if new_comments else ''
            lines.append(f'{format_issue(issue, this_emoji)}{suffix}')
        lines.append('')

    if len(lines) == 1:
        lines.append('none')

    save_snapshots(snapshots, channel_id, issues)

    logger.info('finished digest')
    return '\n'.join(lines)


def update_summary(issues_per_channel: dict[str, List[Issue]]):
    summary_path = root_dir / 'summary.json'

    channels_data = {}
    for channel_name, issues in issues_per_channel.items():
        status_counts = {}
        tag_counts = {}

        for issue in issues:
            status_counts[issue.status] = status_counts.get(issue.status, 0) + 1
            for tag in issue.tags:
                tag_counts[tag.name] = tag_counts.get(tag.name, 0) + 1

        channels_data[channel_name] = {
            'total': len(issues),
            'status': status_counts,
            'tags': tag_counts,
        }

    history = []
    if summary_path.exists():
        try:
            history = json.loads(summary_path.read_text('utf-8'))
        except Exception as e:
            logger.error(f'Error reading summary.json: {e}')
            history = []

    if history and history[-1].get('channels') == channels_data:
        logger.info('Summary unchanged, skipping update.')
        return

    if DRY_RUN:
        logger.info('DRY_RUN, skipping summary.json update.')
        return

    now = datetime.now()
    date_str = now.isoformat()
    new_entry = {
        'date': date_str,
        'channels': channels_data,
    }

    history.append(new_entry)
    summary_path.write_text(json.dumps(history, indent=2), 'utf-8')
    logger.info(f'Summary updated in {summary_path}')


@bot.event
async def on_ready():
    logger.info('starting')
    if DRY_RUN:
        logger.info('DRY RUN!')

    issues_per_channel = {}

    for channel_id, summary_thread_id in CHANNELS_TO_SUMMARIZE.items():
        logger.info(f'processing channel {channel_id}')
        issues = await process_channel(bot, channel_id, summary_thread_id)
        name = CHANNEL_ID_TO_NAME.get(channel_id, str(channel_id))
        issues_per_channel[name] = issues

    update_summary(issues_per_channel)

    logger.info('done')
    await bot.close()


bot.run(sys.argv[1])

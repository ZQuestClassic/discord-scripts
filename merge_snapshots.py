import json

from datetime import datetime
from pathlib import Path


def calculate_stats(issues):
    status_counts = {}
    tag_counts = {}
    for issue in issues:
        status = issue.get('status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1
        for tag in issue.get('tags', []):
            name = tag['name']
            tag_counts[name] = tag_counts.get(name, 0) + 1

    # B/c the Open tag was deleted in these old snapshots
    tag_counts['Open'] = (
        tag_counts.get('Open', 0)
        + status_counts['open']
        - tag_counts.get('Blockers', 0)
        - tag_counts.get('High Priority', 0)
        - tag_counts.get('Low Priority', 0)
    )

    return {'total': len(issues), 'status': status_counts, 'tags': tag_counts}


def main():
    print("Loading snapshots...")
    with open('snapshot-bugs.json', 'r') as f:
        bugs_snapshots = json.load(f)
    with open('snapshot-features.json', 'r') as f:
        features_snapshots = json.load(f)

    summary_path = Path('summary.json')
    if summary_path.exists():
        with open(summary_path, 'r') as f:
            history = json.load(f)
    else:
        history = []

    # Map existing dates to avoid duplicates
    existing_dates = {entry['date'] for entry in history}

    new_entries_count = 0
    # Assuming they are paired by index as they have the same length
    for b_snap, f_snap in zip(bugs_snapshots, features_snapshots):
        # Use average time for the entry date
        avg_time = (b_snap['time'] + f_snap['time']) / 2
        date_str = datetime.fromtimestamp(avg_time).isoformat()

        if date_str in existing_dates:
            continue

        entry = {
            'date': date_str,
            'channels': {
                'bugs': calculate_stats(b_snap['issues']),
                'features': calculate_stats(f_snap['issues']),
            },
        }
        history.append(entry)
        new_entries_count += 1

    # Sort history by date
    history.sort(key=lambda x: x['date'])

    print(f"Added {new_entries_count} new entries.")

    with open('summary.json', 'w') as f:
        json.dump(history, f, indent=2)
    print("summary.json updated.")


if __name__ == '__main__':
    main()

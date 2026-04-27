import json
import re
import os
from pathlib import Path
from datetime import datetime

def parse_log_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract date from filename
    # run-21419123162-2026-01-28T00-00-49Z.log
    match = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)', file_path.name)
    if not match:
        return None
    
    date_part = match.group(1)
    # Convert 2026-01-28T00-00-49Z to 2026-01-28T00:00:49
    t_index = date_part.find('T')
    date_iso = date_part[:t_index] + 'T' + date_part[t_index+1:-1].replace('-', ':')

    channels_data = {}
    
    # Split by processing channel to separate bugs and features
    parts = re.split(r'processing channel (\d+)', content)
    
    id_to_name = {
        '1021382849603051571': 'bugs',
        '1021385902708248637': 'features',
    }

    for i in range(1, len(parts), 2):
        channel_id = parts[i]
        channel_content = parts[i+1]
        channel_name = id_to_name.get(channel_id, channel_id)
        
        counts = {
            'open': 0,
            'pending': 0,
            'unknown': 0,
        }
        tags = {}
        
        # Look for headers like "# Open (361)"
        # Note: some labels have spaces and dashes like "Open - High Priority"
        headers = re.findall(r'# ([\w\s-]+) \((\d+)\)', channel_content)
        if not headers:
            continue

        for label, count_str in headers:
            count = int(count_str)
            if label == 'Open':
                counts['open'] += count
                tags['Open'] = tags.get('Open', 0) + count
            elif label == 'Pending':
                counts['pending'] = count
            elif label == 'Unknown':
                counts['unknown'] = count
            elif label == 'Open - High Priority':
                counts['open'] += count
                tags['High Priority'] = count
                # We also count these as 'Open' tags in the real summary.json usually, 
                # but top_issues.py seems to treat them separately in sections.
            elif label == 'Open - Low Priority':
                counts['open'] += count
                tags['Low Priority'] = count
            elif label == 'Blockers':
                counts['open'] += count
                tags['Blocker'] = count
        
        channels_data[channel_name] = {
            'total': sum(counts.values()), # Note: this total excludes 'closed' issues
            'status': {k: v for k, v in counts.items() if v > 0},
            'tags': tags
        }

    if not channels_data:
        return None

    return {
        'date': date_iso,
        'channels': channels_data,
        'note': 'Scraped from GHA logs; total and status.closed are incomplete.'
    }

def main():
    log_dir = Path('gha-logs')
    summary_path = Path('summary.json')
    
    if summary_path.exists():
        with open(summary_path, 'r') as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []
    else:
        history = []

    existing_dates = {entry['date'] for entry in history}
    
    new_entries = []
    log_files = sorted(list(log_dir.glob('*.log')))
    for log_file in log_files:
        entry = parse_log_file(log_file)
        if entry and entry['date'] not in existing_dates:
            new_entries.append(entry)
            existing_dates.add(entry['date'])
    
    if not new_entries:
        print("No new entries found to add.")
        return

    # Merge and sort by date
    history.extend(new_entries)
    history.sort(key=lambda x: x['date'])
    
    with open(summary_path, 'w') as f:
        json.dump(history, f, indent=2)
    
    print(f"Added {len(new_entries)} new entries to summary.json")

if __name__ == "__main__":
    main()

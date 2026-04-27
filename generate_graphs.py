import json
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

def generate_graphs():
    summary_path = Path('summary.json')
    if not summary_path.exists():
        print("summary.json not found.")
        return

    with open(summary_path, 'r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("Error decoding summary.json")
            return

    if not data:
        print("summary.json is empty.")
        return

    # Prepare data for plotting
    rows = []
    for entry in data:
        date = pd.to_datetime(entry['date'])
        for channel_name, channel_data in entry['channels'].items():
            row = {
                'date': date,
                'channel': channel_name,
                'total': channel_data['total']
            }
            # Add status counts
            for status, count in channel_data.get('status', {}).items():
                row[f'status_{status}'] = count
            # Add tag counts (e.g. priority)
            for tag, count in channel_data.get('tags', {}).items():
                row[f'tag_{tag}'] = count
            rows.append(row)

    df = pd.DataFrame(rows)
    output_dir = Path('graphs')
    output_dir.mkdir(exist_ok=True)

    # 1. Total Issues Over Time
    plt.figure(figsize=(10, 6))
    for channel in df['channel'].unique():
        channel_df = df[df['channel'] == channel]
        plt.plot(channel_df['date'], channel_df['total'], marker='o', label=channel)
    
    plt.title('Total Issues Over Time')
    plt.xlabel('Date')
    plt.ylabel('Count')
    plt.legend()
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(output_dir / 'total_issues.png')
    plt.close()

    # 2. Bug Status Over Time
    if 'bugs' in df['channel'].unique():
        bug_df = df[df['channel'] == 'bugs'].sort_values('date')
        status_cols = [c for c in bug_df.columns if c.startswith('status_')]
        
        if status_cols:
            plt.figure(figsize=(10, 6))
            for col in status_cols:
                status_name = col.replace('status_', '')
                plt.plot(bug_df['date'], bug_df[col].fillna(0), marker='.', label=status_name)
            
            plt.title('Bug Status Trends')
            plt.xlabel('Date')
            plt.ylabel('Count')
            plt.legend()
            plt.grid(True)
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(output_dir / 'bug_status_trends.png')
            plt.close()

    # 3. Feature Request Trends
    if 'features' in df['channel'].unique():
        feat_df = df[df['channel'] == 'features'].sort_values('date')
        plt.figure(figsize=(10, 6))
        plt.plot(feat_df['date'], feat_df['total'], color='green', marker='s', label='Features')
        plt.title('Total Feature Requests Over Time')
        plt.xlabel('Date')
        plt.ylabel('Count')
        plt.grid(True)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(output_dir / 'feature_trends.png')
        plt.close()

    print(f"Graphs generated in the '{output_dir}' directory.")

if __name__ == "__main__":
    generate_graphs()

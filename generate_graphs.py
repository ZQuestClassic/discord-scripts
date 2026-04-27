import json

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


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

    # 2. Bug Status Over Time (Stacked)
    if 'bugs' in df['channel'].unique():
        bug_df = df[df['channel'] == 'bugs'].sort_values('date')
        # Define a consistent order for stacking
        desired_statuses = ['open', 'pending']
        status_cols = [f'status_{s}' for s in desired_statuses if f'status_{s}' in bug_df.columns]
        
        if status_cols:
            plt.figure(figsize=(12, 7))
            labels = [col.replace('status_', '').capitalize() for col in status_cols]
            y = [bug_df[col].fillna(0).values for col in status_cols]
            
            plt.stackplot(bug_df['date'], y, labels=labels, alpha=0.8)
            
            plt.title('Active Bug Status Trends (Stacked)')
            plt.xlabel('Date')
            plt.ylabel('Count')
            plt.legend(loc='upper left')
            plt.grid(True, alpha=0.3)
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(output_dir / 'bug_status_trends_stacked.png')
            plt.close()

    # 3. Feature Request Trends (Stacked)
    if 'features' in df['channel'].unique():
        feature_df = df[df['channel'] == 'features'].sort_values('date')
        # Define a consistent order for stacking
        desired_statuses = ['open', 'pending', 'unknown']
        status_cols = [f'status_{s}' for s in desired_statuses if f'status_{s}' in feature_df.columns]
        
        if status_cols:
            plt.figure(figsize=(12, 7))
            labels = [col.replace('status_', '').capitalize() for col in status_cols]
            y = [feature_df[col].fillna(0).values for col in status_cols]
            
            plt.stackplot(feature_df['date'], y, labels=labels, alpha=0.8)
            
            plt.title('Active Feature Status Trends (Stacked)')
            plt.xlabel('Date')
            plt.ylabel('Count')
            plt.legend(loc='upper left')
            plt.grid(True, alpha=0.3)
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(output_dir / 'feature_status_trends_stacked.png')
            plt.close()

    # 4. Top Bug Tags Over Time
    if 'bugs' in df['channel'].unique():
        bug_df = df[df['channel'] == 'bugs'].sort_values('date')
        tag_cols = [c for c in bug_df.columns if c.startswith('tag_')]
        if tag_cols:
            # Find top 10 tags by their latest count
            latest_counts = bug_df[tag_cols].iloc[-1].fillna(0).sort_values(ascending=False)
            top_tags = latest_counts.head(10).index.tolist()
            
            plt.figure(figsize=(12, 7))
            labels = [col.replace('tag_', '') for col in top_tags]
            y = [bug_df[col].fillna(0).values for col in top_tags]
            
            plt.stackplot(bug_df['date'], y, labels=labels, alpha=0.7)
            plt.title('Top Bug Tag Trends (Stacked)')
            plt.xlabel('Date')
            plt.ylabel('Count')
            plt.legend(loc='upper left', bbox_to_anchor=(1, 1))
            plt.grid(True, alpha=0.3)
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(output_dir / 'bug_tag_trends.png')
            plt.close()

    # 5. Top Feature Tags Over Time
    if 'features' in df['channel'].unique():
        feature_df = df[df['channel'] == 'features'].sort_values('date')
        tag_cols = [c for c in feature_df.columns if c.startswith('tag_')]
        if tag_cols:
            # Find top 10 tags by their latest count
            latest_counts = feature_df[tag_cols].iloc[-1].fillna(0).sort_values(ascending=False)
            top_tags = latest_counts.head(10).index.tolist()
            
            plt.figure(figsize=(12, 7))
            labels = [col.replace('tag_', '') for col in top_tags]
            y = [feature_df[col].fillna(0).values for col in top_tags]
            
            plt.stackplot(feature_df['date'], y, labels=labels, alpha=0.7)
            plt.title('Top Feature Tag Trends (Stacked)')
            plt.xlabel('Date')
            plt.ylabel('Count')
            plt.legend(loc='upper left', bbox_to_anchor=(1, 1))
            plt.grid(True, alpha=0.3)
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(output_dir / 'feature_tag_trends.png')
            plt.close()

    print(f"Graphs generated in the '{output_dir}' directory.")

if __name__ == "__main__":
    generate_graphs()

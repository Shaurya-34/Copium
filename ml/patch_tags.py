import pandas as pd
import random

# Load your existing data
df = pd.read_csv("aws_mock_data.csv")

# Define our professional dimensions
teams = ['Backend-API', 'Data-Science', 'Frontend-Web', 'Infrastructure']
environments = ['Production', 'Development', 'Staging']
projects = ['Project-Alpha', 'Project-Omega', 'Internal-Tools']

# Randomly assign tags to each unique Resource ID
resource_ids = df['resource_id'].unique()
tag_map = {res: {
    'team': random.choice(teams),
    'environment': random.choice(environments),
    'project': random.choice(projects)
} for res in resource_ids}

# Map these tags back to the main dataframe
df['team'] = df['resource_id'].map(lambda x: tag_map[x]['team'])
df['environment'] = df['resource_id'].map(lambda x: tag_map[x]['environment'])
df['project'] = df['resource_id'].map(lambda x: tag_map[x]['project'])

# Save the updated dataset
df.to_csv("aws_mock_data.csv", index=False)
print("✅ Checkpoint 6: Environment, Team, and Project tags injected into aws_mock_data.csv!")
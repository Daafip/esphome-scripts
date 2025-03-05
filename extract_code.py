# extract api keys from yaml files in the same directory as this script
# and print them to the console
# to store in secrets
from pathlib import Path

lst = list(Path(__file__).parent.glob("*.yaml"))

output = {}
for file in lst:
    with open(file, "r") as f:
        data = f.readlines()
        for line in data: 
            if "key:" in line: 
                output[f'{file.name.split(".")[0]}_ota_key'] = line.split(":")[1].strip()

for key in output: 
    print(f'{key}: {output[key]}')
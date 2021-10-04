import sys
import os
import json
import http.client

source_workspaces = {}

loadFromDumpFile = True
if (loadFromDumpFile): # load the workspace info from a dump file
    print("Grabbing workspaces from Dump File...")
    source_workspaces = json.load(open("SourceWorkspaces.json"))

workspacesToGrab = json.load(open("WorkspacesToMigrate.json"))["workspaces"]

source_workspacesToGrab = []

for source_workspace in source_workspaces:
    for workspace in workspacesToGrab:
        if (workspace in source_workspace["attributes"]["name"]):
            print(source_workspace["attributes"]["name"])
            source_workspacesToGrab.append(source_workspace)

print(len(source_workspacesToGrab))
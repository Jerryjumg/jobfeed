#!/bin/zsh
# Double-click (macOS) to fetch today's jobs and open the spreadsheet.
cd "$(dirname "$0")"
python3 jobfeed.py && open "$(cat last_output.txt)"

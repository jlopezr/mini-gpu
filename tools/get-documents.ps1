Get-ChildItem . -Recurse -File -Filter *.md |                                 
    Where-Object { $_.FullName -notmatch '[\\/](\.venv|y\.lcc|x\.tests)[\\/]' } |
    Format-Table FullName -AutoSize
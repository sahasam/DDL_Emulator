
### File Sync for Python Source Code

Zip local dir and listen on tcp port for connections:

    tar -cpv ./ | nc -l 45454


Open connection over tcp and unzip content from connection:

    nc -w 10 169.254.103.201 | tar -xpv

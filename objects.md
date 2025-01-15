# Link is operating normally
```json
{
    "type": "update",
    "snapshots": {
        "alice": {
            "name": "alice",
            "ip": "127.0.0.1",
            "port": 55550,
            "type": "client",
            "link": {
                "status": "connected",
                "statistics": {
                    "events": 56,
                    "round_trip_latency": 0.00004244275372143617,
                    "pps": 23561.147953860007
                }
            }
        },
        "bob": {
            "name": "bob",
            "ip": "127.0.0.1",
            "port": 55550,
            "type": "server",
            "link": {
                "status": "connected",
                "statistics": {
                    "events": 14,
                    "round_trip_latency": 0.00004242243050922267,
                    "pps": 23572.43533659862
                }
            }
        }
    }
}
```

# Link is disconnected
```json
{
    "type": "update",
    "snapshots": {
        "alice": {
            "name": "alice",
            "ip": "127.0.0.1",
            "port": 55550,
            "type": "client",
            "link": {
                "status": "disconnected",
                "statistics": {
                    "events": 0,
                    "round_trip_latency": 999999,
                    "pps": 0
                }
            }
        },
        "bob": {
            "name": "bob",
            "ip": "127.0.0.1",
            "port": 55550,
            "type": "server",
            "link": {
                "status": "disconnected",
                "statistics": {
                    "events": 0,
                    "round_trip_latency": 999999,
                    "pps": 0
                }
            }
        }
    }
}
```

# Commands
Reported by the client to break a link
```json
{
    "action": "DROP",
    "port": "alice
}
```

```json
{
    "action": "DROP",
    "port": "bob
}
```

#### Not currently supported
```json
{
    "action": "TOGGLE_ENABLED",
    "port": "alice|bob|etc..."
}
```
```json
{
    "action": "SET_STATE",
    "port": "alice|bob|etc..."
    "state": "CONNECT/DISCONNECT/UNIDIR0/UNIDIR1"
}
```

# Command ACK
Reported by the server after receiving a DROP command
```json
{
    "status": "message received"
}
```


# Data Ranges

#### pps

When running, the pps should be between 15000 and 30000. Otherwise, it's at 0

#### round_trip_latency

When running, the round_trip_latency should be between 35 and 45 us. Otherwise, it's at 999999s

#### events

When running, the events doesn't seem to be updating properly on the websocket, but it's reporting the logs correctly. Ignore this field for now
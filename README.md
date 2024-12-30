# Hermes

Hermes is a network simulation framework for testing and developing network protocols.

## Usage

To run a simulation, use the following command:

```bash
# Create a virtual environment
python3 -m venv env
source env/bin/activate # On Windows, use `env\Scripts\activate`
pip install -r requirements.txt

# Run the simulation
python3 src/main.py -c <path_to_config_file> -l <path_to_log_dir>
```

## WebSocket Server

The WebSocket server is used to send updates to the client, and to receive commands from the client. It is automatically started when the simulation is started on port 6363.

To send commands to the server, you can use the following command:

```bash
echo '{"port":"alice","action":"DROP"}' | websocat ws://localhost:6363
```

To receive updates from the server, you can use the following command:

```bash
websocat ws://localhost:6363
```

The server will send updates to the client in the following format:

```json
{"type":"update","snapshots":[]}
```

The snapshots are the state of the ports at the time the update was sent. Each snapshot is a dictionary with the following keys:

- `name`: The name of the port.
- `ip`: The IP address of the port.
- `port`: The port number of the port.
- `type`: The type of the port. Can be `client` or `server`.
- `link`: The link status of the port.
    - `status`: The status of the link. Can be `connected` or `disconnected`.
    - `statistics`: The statistics of the link.
        - `events`: The number of events that have occurred on the link.
        - `round_trip_latency`: The round trip latency of the link.
        - `pps`: The packets per second of the link.

## Config

The config is a Yaml file that describes the simulation process. You can run an entire network in a single simulation, or just run the ports and threads of a single node.

In the config, there are two kinds of ports: client and server. Clients are the ports that will be initiating connections to the server. If you are emulating multiple links on a single host, you can separate the client and server pairs into different ports. This will half performance, but it will allow you to run multiple links on a single host.

- `name`: The name of the port. This is used to identify the port in the simulation.
- `ip`: The IP address of the port. On the client side, this is the address target of the server. On the server side, this is the IP that the server will bind to.
- `port`: The channel on which the link will be created. 
- `type`: The type of the port. Can be `client` or `server`.

```yaml
ports:
  - name: alice
    ip: 127.0.0.1
    port: 55550
    type: client
  - name: bob
    ip: 127.0.0.1
    port: 55550
    type: server
  - name: charlie
    ip: 127.0.0.1
    port: 55551
    type: client
  - name: dugan
    ip: 127.0.0.1
    port: 55551
    type: server
```





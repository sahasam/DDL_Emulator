import select
import threading
import os
import pickle

from hermes.machines.data import Data

class PipeQueue:
    def __init__(self):
        # Create pipe for both signaling and data transfer
        self.read_fd, self.write_fd = os.pipe()
        # Make read end non-blocking
        os.set_blocking(self.read_fd, False)
    
    def put(self, item):
        """Serialize and write the item to the pipe."""
        # Pickle the data and prefix with length for framing
        data = pickle.dumps(item)
        length = len(data).to_bytes(4, 'big')
        # Write atomically (length + data) to avoid interleaving
        os.write(self.write_fd, length + data)
    
    def get(self):
        """Read and deserialize an item from the pipe."""
        try:
            # Read the length prefix (4 bytes)
            length_bytes = os.read(self.read_fd, 4)
            if not length_bytes:
                return None
            length = int.from_bytes(length_bytes, 'big')
            
            # Read the actual data
            data = os.read(self.read_fd, length)
            return pickle.loads(data)
        except BlockingIOError:
            return None
    
    @property
    def fileno(self):
        """Return the file descriptor for select() compatibility."""
        return self.read_fd
    
    def close(self):
        """Clean up the pipe file descriptors."""
        os.close(self.read_fd)
        os.close(self.write_fd)
    
    def empty(self):
        """Return True if there is no data available to read, False otherwise."""
        ready, _, _ = select.select([self.read_fd], [], [], 0)
        return len(ready) == 0



class TreeAlgorithm(threading.Thread):
    PROTOCOL_ID = 'TREE'

    def __init__(self, port_manager):
        super().__init__()
        self.tree = {
            'nodes': [],
            'edges': [],
        }
        self.tree_slots = {}
        self.port_manager = port_manager
    
    def run(self):
        read_queues = []
        signal_queues = []
        for _, port in self.port_manager.ports.items():
            read_queues.append((port.name, port.read_q))
            signal_queues.append((port.name, port.signal_q))
        
        all_queues = read_queues + signal_queues
        
        while True:
            try:
                # Get file descriptors for select
                queue_fds = [q[1].fileno for q in all_queues]
                ready_fds, _, _ = select.select(queue_fds, [], [])

                # Process all queues that have data
                for port_name, q in all_queues:
                    if q.fileno in ready_fds:
                        data = q.get()
                        if data is not None:
                            if (port_name, q) in read_queues:
                                self.handle_read_message(data, port_name)
                            else:  # signal queue
                                self.handle_signal_message(data, port_name)
            except select.error as e:
                print(f"Select error: {e}")
                break

    def handle_read_message(self, data: Data, port_id: str):
        """Process messages from read queues"""
        # ALGORITHM MESSAGES
        # 1. TREE_BUILD -> if the node has not seen this tree build packet before,
        #    forward it to all other nodes. If it has seen it, then isolate and mark
        #    the port as unused for that tree. If you are the last cell on the tree,
        #    then send a TREE_BOUNDARY along the rootward port for that tree.
        # 2. TREE_BOUNDARY -> forward the TREE_BOUNDARY packet along to the rootward
        #    port of that tree. Add node-hop information to the packet. If you are the
        #    root, then accumulate the boundary information into a DAG.
        content = data.content
        # Increment letter in content, wrapping from z back to a
        letter = content.decode('utf-8')
        if letter == 'z':
            content = b'a'
        else:
            content = bytes([ord(letter) + 1])
        data.content = content

        self.send_to_port(data, port_id)
        # if data.type == 'TREE_BUILD':
        #     if data.tree_id not in self.tree_slots:
        #         self.tree_slots[data.tree_id] = [port_id]
        #         self.send_broadcast(data, exclude=[port_id])
        #     else:
        #         self.tree_slots[data.tree_id].append(port_id)
        # elif data.type == 'TREE_BOUNDARY':
        #     if data.tree_id == self.root_tree_id:
        #         self.accumulate_boundary(data)
        #     rootward_port = self.tree_slots[data.tree_id][0]
        #     self.ports[rootward_port][1].put(data)

    def handle_signal_message(self, data: Data, port_id: str):
        """Process messages from signal queues"""
        # Implement your signal message handling logic here
        # SIGNAL MESSAGES
        # 1. CONNECTED -> port has established a link. Initiate a tree build.
        # 2. DISCONNECTED -> port has lost a link. Initiate failover.
        print(f"[TREE][handle_signal_message] received from {port_id}: {data}")
        pass

    def send_broadcast(self, data: Data, exclude: list[str]):
        write_queues = []
        for port_name, port in self.port_manager.ports.items():
            if port_name not in exclude:
                write_queues.append(port.write_q)
        for q in write_queues:
            q.put(data)
    
    def send_to_port(self, data: Data, port_name: str):
        port = self.port_manager.ports[port_name]
        port.write_q.put(data)

    def accumulate_boundary(self, data: Data):
        pass




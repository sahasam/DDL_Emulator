import hashlib
import select
import threading
import os
import pickle
import time

from hermes.machines.data import Data, TreeBoundaryData, TreeBuildData

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
        self.root_name = os.environ.get('NODE_NAME')
        self.tree = {
            'nodes': ["ME"],
            'edges': [],
        }
        self.tree_slots = {}
        self.tree_slots_lock = threading.Lock()
        self.port_manager_lock = threading.Lock()  # Add lock for port_manager
        self.alive_port_ids = []
        self.port_manager = port_manager
        self.root_tree_id = hashlib.sha256(os.urandom(16)).hexdigest()
        self.tree_boundary_data = []

    def run(self):
        read_queues = []
        signal_queues = []
        with self.port_manager_lock:
            for _, port in self.port_manager.ports.items():
                read_queues.append((port.name, port.read_q))
                signal_queues.append((port.name, port.signal_q))
        
        all_queues = read_queues + signal_queues

        # Start periodic tree build in a separate thread
        tree_build_thread = threading.Thread(target=self._run_periodic_tree_build)
        tree_build_thread.daemon = True
        tree_build_thread.start()
        
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
                # print(f"Select error: {e}")
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
        # # print(f"[TREE][handle_read_message] received from {port_id}: {data}")

        # if isinstance(data, Data):
        #     if data.content == b'a':
        #         return

        # if isinstance(data, TreeBuildData) and data.type == 'TREE_BUILD':
        #     if port_id not in self.alive_port_ids:
        #         self.alive_port_ids.append(port_id)
    
        #     with self.tree_slots_lock:
        #         if data.tree_id not in self.tree_slots:
        #             self.tree_slots[data.tree_id] = [(port_id, data.hop_count)]
        #             self.send_broadcast(TreeBuildData(type='TREE_BUILD', tree_id=data.tree_id, hop_count=data.hop_count+1, exclude=[port_id]))
        #         elif (port_id, data.hop_count) == self.tree_slots[data.tree_id][0]: # root is retrying tree_build
        #             self.send_broadcast(TreeBuildData(type='TREE_BUILD', tree_id=data.tree_id, hop_count=data.hop_count+1, exclude=[port_id]))
        #         elif port_id not in [port_id for port_id, _ in self.tree_slots[data.tree_id]]:
        #             self.tree_slots[data.tree_id].append((port_id, data.hop_count))
        #             self.send_broadcast(TreeBuildData(type='TREE_BUILD', tree_id=data.tree_id, hop_count=data.hop_count+1, exclude=[port_id]))
        #         elif port_id in self.tree_slots[data.tree_id]:
        #             # Find existing entry for this port_id
        #             existing_entry = next((i for i, (p, h) in enumerate(self.tree_slots[data.tree_id]) if p == port_id), None)
        #             if existing_entry is not None:
        #                 # Only update if new hop count is higher
        #                 if data.hop_count > self.tree_slots[data.tree_id][existing_entry][1]:
        #                     self.tree_slots[data.tree_id][existing_entry] = (port_id, data.hop_count)
                        

        #         # print(f"[TREE][handle_read_message] tree_slots={self.tree_slots[data.tree_id]} alive_port_ids={self.alive_port_ids}")
        #         if len(self.tree_slots[data.tree_id]) == len(self.alive_port_ids):
        #             # print(f"[TREE][handle_read_message] sending tree_boundary to {self.tree_slots[data.tree_id][0]}")
        #             self.send_to_port(
        #                 TreeBoundaryData(tree_id=data.tree_id, node_hop=[self.root_name]),
        #                 self.tree_slots[data.tree_id][0][0]
        #             )
    
        # elif isinstance(data, TreeBoundaryData) and data.type == 'TREE_BOUNDARY':
        #     if self.root_tree_id.startswith(data.tree_id):
        #         self.accumulate_boundary(data)
        #     else:
        #         self.send_to_port(
        #             TreeBoundaryData(tree_id=data.tree_id, node_hop=data.node_hop + [self.root_name]),
        #             self.tree_slots[data.tree_id][0][0]
        #         )
        # # print(f"[TREE][handle_read_message] received from {port_id}: {data}")
        if isinstance(data, TreeBuildData) and data.type == 'TREE_BUILD':
            if port_id not in self.alive_port_ids:
                self.alive_port_ids.append(port_id)
            
            with self.tree_slots_lock:
                if data.ttl == 5 and data.hop_count < data.ttl:
                    self.send_broadcast(
                        TreeBuildData(type='TREE_BUILD',
                                      tree_id=data.tree_id,
                                      hop_count=data.hop_count+1,
                                      ttl=data.ttl),
                        exclude=[port_id]
                    )
                    # print(f"[TREE][handle_read_message] clearing tree_slots for {data.tree_id}")
                    if data.tree_id in self.tree_slots:
                        del self.tree_slots[data.tree_id]
                elif data.hop_count < data.ttl:
                   self.send_broadcast(
                        TreeBuildData(type='TREE_BUILD',
                                      tree_id=data.tree_id,
                                      hop_count=data.hop_count+1,
                                      ttl=data.ttl),
                        exclude=[port_id]
                    ) 
                elif data.ttl == data.hop_count:
                    return
                
                # store incoming direction of first tree packet on the node.
                if data.tree_id not in self.tree_slots:
                    self.tree_slots[data.tree_id] = [(port_id, data.hop_count)]
                    # send tree boundary rootward.
                    self.send_to_port(
                        TreeBoundaryData(tree_id=data.tree_id, node_hop=[self.root_name]),
                        port_id
                    )
                
        elif isinstance(data, TreeBoundaryData) and data.type == 'TREE_BOUNDARY':
            # print(f"[TREE][handle_read_message] received tree boundary from {port_id}: {data}")
            if self.root_tree_id.startswith(data.tree_id):
                self.accumulate_boundary(data)
            else:
                if len(data.node_hop) > 4:
                    # print(f"[TREE][handle_read_message] skipping tree boundary from {port_id}: {data}. node hop too long")
                    return
                with self.tree_slots_lock:
                    if data.tree_id not in self.tree_slots:
                        # print(f"[TREE][handle_read_message] skipping tree boundary from {port_id}: {data}. tree_id not in tree_slots")
                        return
                    self.send_to_port(
                        TreeBoundaryData(tree_id=data.tree_id, node_hop=data.node_hop + [self.root_name]),
                        self.tree_slots[data.tree_id][0][0]
                    ) 

    
    def _run_periodic_tree_build(self):
       while True:
            self.tree_boundary_data = []
            self.tree = {
                'nodes': ["ME"],
                'edges': [],
            }

            with self.tree_slots_lock:
                self.root_tree_id = hashlib.sha256(os.urandom(16)).hexdigest()
            
            for i in range(1, 6):
                self.send_broadcast(
                    TreeBuildData(
                        type='TREE_BUILD',
                        tree_id=self.root_tree_id,
                        hop_count=0,
                        ttl=i
                    ))
                time.sleep(0.01)

            time.sleep(0.3)
            with self.port_manager_lock:
                print(f"[TREE][_run_periodic_tree_build] tree={self.tree}")
                self.port_manager.set_tree(self.tree)

    def handle_signal_message(self, data: Data, port_id: str):
        """Process messages from signal queues"""
        # Implement your signal message handling logic here
        # SIGNAL MESSAGES
        # 1. CONNECTED -> port has established a link. Initiate a tree build.
        # 2. DISCONNECTED -> port has lost a link. Initiate failover.
        # print(f"[TREE][handle_signal_message] received from {port_id}: {data}")
        if data.content == b'CONNECTED':
            if port_id not in self.alive_port_ids:
                self.alive_port_ids.append(port_id)
            # print(f"[TREE][handle_signal_message] Port {port_id} connected")
        elif data.content == b'DISCONNECTED':
            if port_id in self.alive_port_ids:
                self.alive_port_ids.remove(port_id)
            
            with self.tree_slots_lock:
                for tree_id in list(self.tree_slots.keys()):  # Create a copy of keys to avoid modification during iteration
                    if self.tree_slots[tree_id][0][0] == port_id:
                        self.tree_slots[tree_id].remove(self.tree_slots[tree_id][0])
                        if len(self.tree_slots[tree_id]) == 0:
                            del self.tree_slots[tree_id]
                        else:
                            self.send_to_port(
                                TreeBoundaryData(tree_id=tree_id, node_hop=[self.root_name]),
                                self.tree_slots[tree_id][0][0]
                            )
                    elif port_id in [port_id for port_id, _ in self.tree_slots[tree_id]]:
                        self.tree_slots[tree_id] = [(p, h) for p, h in self.tree_slots[tree_id] if p != port_id]

            # print(f"[TREE][handle_signal_message] Port {port_id} disconnected")
        
        # Initiate a tree build on any disconnection changes
        # self.tree = {
        #     'nodes': ["ME"],
        #     'edges': [],
        # }
        # with self.port_manager_lock:
        #     self.port_manager.set_tree(self.tree)
        # self.tree_boundary_data = []
        # self.send_broadcast(TreeBuildData(type='TREE_BUILD', tree_id=self.root_tree_id))

    def send_broadcast(self, data: Data, exclude: list[str]=[]):
        write_queues = []
        with self.port_manager_lock:
            for port_name in self.alive_port_ids:
                if port_name not in exclude:
                    write_queues.append(self.port_manager.ports[port_name].write_q)
        for q in write_queues:
            q.put(data)
    
    def send_to_port(self, data: Data, port_name: str):
        with self.port_manager_lock:
            port = self.port_manager.ports[port_name]
            port.write_q.put(data)

    def accumulate_boundary(self, data: Data):
        """Accumulate boundary paths into the tree representation"""
        # Check for loops or self-references in the path
        seen_nodes = set()
        for node in data.node_hop:
            if node in seen_nodes or node == self.root_name:
                return
            seen_nodes.add(node)
        
        path = data.node_hop
        
        # Add nodes if they don't exist
        for node in path:
            if node not in self.tree['nodes']:
                self.tree['nodes'].append(node)
        
        # Track which nodes are already connected in the tree
        connected_nodes = {self.tree['nodes'].index("ME")}  # Root is always connected
        for edge in self.tree['edges']:
            connected_nodes.add(edge[1])  # Add all nodes that have parents
        
        # Only connect first node to root if this is a direct boundary report
        if len(path) == 1:
            first_node = path[0]
            root_idx = self.tree['nodes'].index("ME")
            first_node_idx = self.tree['nodes'].index(first_node)
            root_edge = (root_idx, first_node_idx)
            # Remove any reverse edges before adding the correct one
            reverse_edge = (first_node_idx, root_idx)
            if reverse_edge in self.tree['edges']:
                self.tree['edges'].remove(reverse_edge)
            if root_edge not in self.tree['edges']:
                self.tree['edges'].append(root_edge)
            connected_nodes.add(first_node_idx)
        
        # Add edges between consecutive nodes in path
        for i in range(len(path) - 1):
            child = path[i]
            parent = path[i + 1]
            child_idx = self.tree['nodes'].index(child)
            
            # Skip if this node is already connected in the tree
            if child_idx in connected_nodes:
                continue
            
            parent_idx = self.tree['nodes'].index(parent)
            edge = (parent_idx, child_idx)
            reverse_edge = (child_idx, parent_idx)
            
            # Remove any reverse edges before adding the correct one
            if reverse_edge in self.tree['edges']:
                self.tree['edges'].remove(reverse_edge)
            if edge not in self.tree['edges']:
                self.tree['edges'].append(edge)

        # Add any new nodes that aren't already in the tree
        # for node in data.node_hop:
        #     if node not in self.tree['nodes']:
        #         # Find the correct position to insert alphabetically, but after "ME"
        #         insert_pos = 1  # Start after "ME"
        #         for i in range(1, len(self.tree['nodes'])):
        #             if node < self.tree['nodes'][i]:
        #                 insert_pos = i
        #                 break
        #             insert_pos = i + 1
                
        #         # Before inserting, store old indices of nodes that will shift
        #         old_to_new = {}
        #         for i in range(insert_pos, len(self.tree['nodes'])):
        #             old_to_new[i] = i + 1
                
        #         # Insert the new node
        #         self.tree['nodes'].insert(insert_pos, node)
                
        #         # Update edges with new indices
        #         updated_edges = []
        #         for edge in self.tree['edges']:
        #             new_edge = (
        #                 old_to_new.get(edge[0], edge[0]),
        #                 old_to_new.get(edge[1], edge[1])
        #             )
        #             updated_edges.append(new_edge)
        #         self.tree['edges'] = updated_edges


        # Initialize connected_nodes with ALL nodes that already have a parent
        # connected_nodes = {self.tree['nodes'].index("ME")}
        # for edge in self.tree['edges']:
        #     connected_nodes.add(edge[1])  # Add all nodes that have parents
        
        # # Process path from root to leaf, only adding edges for new connections
        # path_indices = [self.tree['nodes'].index(node) for node in data.node_hop]
        # path_indices.reverse()  # Process from leaf to root
        
        # for i in range(len(path_indices)):
        #     current_node = path_indices[i]
        #     if current_node not in connected_nodes:
        #         # First try to connect to the closest ancestor in the path
        #         connected_in_path = False
        #         for j in range(i + 1, len(path_indices)):
        #             potential_parent = path_indices[j]
        #             if potential_parent in connected_nodes:
        #                 edge = (potential_parent, current_node)
        #                 if edge not in self.tree['edges']:
        #                     self.tree['edges'].append(edge)
        #                 connected_nodes.add(current_node)
        #                 connected_in_path = True
        #                 break
                
        #         # If no ancestor in path, connect to root
        #         if not connected_in_path:
        #             root_idx = self.tree['nodes'].index("ME")
        #             edge = (root_idx, current_node)
        #             if edge not in self.tree['edges']:
        #                 self.tree['edges'].append(edge)
        #             connected_nodes.add(current_node)

        # with self.port_manager_lock:
        #     self.port_manager.set_tree(self.tree)




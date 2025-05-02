from typing import Optional


class PathNode:
    def __init__(self, portid: str, parent: Optional['PathNode'] = None):
        self.portid = portid
        self.children: dict[str, PathNode] = {}
        self.parent: PathNode | None = parent

class PathTree:
    def __init__(self, tree_id: str, tree_instance_id: str):
        self.tree_id = tree_id
        self.tree_instance_id = tree_instance_id
        self.root: PathNode = PathNode(tree_id)
    
    def accumulate_path(self, path: list[str]):
        current_node = self.root
        for portid in path:
            if portid not in current_node.children:
                current_node.children[portid] = PathNode(portid, current_node)
            current_node = current_node.children[portid]
    
    def serialize(self):
        """Serialize the tree into nodes and edges using BFS traversal"""
        nodes = []
        edges = []
        visited = set()
        
        # BFS queue starting with root
        queue = [self.root]
        
        while queue:
            current = queue.pop(0)
            
            # Only process each node once
            if current.portid in visited:
                continue
                
            visited.add(current.portid)
            
            # Add node
            nodes.append(current.portid)
            
            # Add edge from parent if it exists
            if current.parent:
                edges.append({
                    'source': current.parent.portid,
                    'target': current.portid
                })
            
            # Add all children to queue
            queue.extend(current.children.values())
            
        return {
            'nodes': nodes,
            'edges': edges
        }

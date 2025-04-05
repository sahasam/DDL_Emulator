import os
import pickle
import select


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
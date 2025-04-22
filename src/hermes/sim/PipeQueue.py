import os
import pickle
import select
import fcntl
import errno
import logging


class PipeQueue:
    def __init__(self):
        # Create pipe for both signaling and data transfer
        self.read_fd, self.write_fd = os.pipe()
        # Make read end non-blocking
        os.set_blocking(self.read_fd, False)
        self.logger = logging.getLogger(__name__)
    
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
        """Close the pipe queue"""
        try:
            # First check if descriptors are still valid
            if self.read_fd is not None and self.write_fd is not None:
                # Check if fd is still valid
                try:
                    flags = fcntl.fcntl(self.read_fd, fcntl.F_GETFD)
                    os.close(self.read_fd)
                except OSError as e:
                    if e.errno != errno.EBADF:  # Only log if error is not "bad file descriptor"
                        self.logger.warning(f"Error closing read_fd: {e}")
                
                try:
                    flags = fcntl.fcntl(self.write_fd, fcntl.F_GETFD)
                    os.close(self.write_fd)
                except OSError as e:
                    if e.errno != errno.EBADF:  # Only log if error is not "bad file descriptor"
                        self.logger.warning(f"Error closing write_fd: {e}")
                
                self.read_fd = None
                self.write_fd = None
        except Exception as e:
            self.logger.warning(f"Error during pipe cleanup: {e}")
    
    def empty(self):
        """Return True if there is no data available to read, False otherwise."""
        ready, _, _ = select.select([self.read_fd], [], [], 0)
        return len(ready) == 0
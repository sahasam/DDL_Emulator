Q, T, P0, P1, B0, B1, R0, R1 = 1, 2, 3, 4, 5, 6, 7, 8
A0, A1, A2, A3, A4, A5, A6, A7 = 9, 10, 11, 12, 13, 14, 15, 16
xx = 17

statename = {1:"Q", 2:"T", 3:"P0", 4:"P1", 5:"B0", 6:"B1", 7:"R0", 8:"R1",
             9:"A0", 10:"A1", 11:"A2", 12:"A3", 13:"A4", 14:"A5", 15:"A6", 16:"A7",
             17:"xx", 18:"gamma", 19:"dash"}

class FSPStateColors:
    """Complete Wakesman FSP state color mapping for StreamDeck"""

    # Main state colors - distinct and visually appealing
    STATE_COLORS = {
        # Core states
        Q:  (240, 240, 240),    # Light gray - Quiescent (most common)
        T:  (255, 255, 0),      # BRIGHT YELLOW - FIRING! 🔥
        xx: (0, 0, 0),          # Black - Edge/Invalid
        
        # General states  
        P0: (255, 0, 0),        # Red - General initial
        P1: (255, 100, 100),    # Light red - General secondary
        
        # Border states
        B0: (0, 0, 255),        # Blue - Border primary
        B1: (100, 100, 255),    # Light blue - Border secondary
    
        # Ready states
        R0: (128, 0, 128),      # Purple - Ready primary  
        R1: (200, 100, 200),    # Light purple - Ready secondary
        
        # Action states (green family for progression)
        A0: (0, 255, 0),        # Bright green
        A1: (50, 255, 50),      # Light green
        A2: (0, 200, 0),        # Medium green  
        A3: (100, 255, 100),    # Pale green
        A4: (0, 150, 0),        # Dark green
        A5: (150, 255, 150),    # Very pale green
        A6: (0, 255, 150),      # Green-cyan
        A7: (150, 255, 0),      # Yellow-green
    }
    
    # Role-based color modifiers
    ROLE_MODIFIERS = {
        'general': (1.0, 0.8, 0.8),     # Slight red tint
        'left_edge': (0.5, 0.5, 0.5),   # Dimmed
        'right_edge': (0.5, 0.5, 0.5),  # Dimmed  
        'soldier': (1.0, 1.0, 1.0),     # Normal
    }
    
    @classmethod
    def get_color_for_state(cls, fsp_state, role='soldier'):
        """Get RGB color for FSP state and role"""
        base_color = cls.STATE_COLORS.get(fsp_state, (128, 128, 128))  # Default gray
        modifier = cls.ROLE_MODIFIERS.get(role, (1.0, 1.0, 1.0))
        
        # Apply role modifier
        final_color = tuple(
            min(255, int(base_color[i] * modifier[i])) 
            for i in range(3)
        )
        
        return final_color
    
    @classmethod  
    def get_firing_animation_colors(cls):
        """Get animation sequence for firing state"""
        return [
            (255, 255, 0),    # Yellow
            (255, 255, 255),  # White flash
            (255, 255, 0),    # Yellow
            (255, 255, 255),  # White flash
            (255, 255, 0),    # Yellow (final)
        ]
    
    @classmethod
    def get_state_name(cls, fsp_state):
        """Get human-readable name for FSP state"""
        names = {
            Q: "Quiescent", T: "🔥 FIRED! 🔥", xx: "Edge",
            P0: "General Start", P1: "General Ready",
            B0: "Border 1", B1: "Border 2", 
            R0: "Ready 1", R1: "Ready 2",
            A0: "Action 1", A1: "Action 2", A2: "Action 3", A3: "Action 4",
            A4: "Action 5", A5: "Action 6", A6: "Action 7", A7: "Action 8"
        }
        return names.get(fsp_state, f"State {fsp_state}")
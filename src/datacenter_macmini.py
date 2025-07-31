from datacenter import ProtoDatacenter


if __name__ == "__main__":
    try:
        dc = ProtoDatacenter()
        dc.load_topology('topology_macmini1.json')
    finally:
        for cell_id in list(dc.cells.keys()):
                dc.remove_cell(cell_id)
                
            
    
    
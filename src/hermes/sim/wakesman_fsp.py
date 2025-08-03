#!/usr/bin/env python

import sys
from enum import Enum
import csv
from io import StringIO
from optparse import OptionParser

statename = {1:"Q", 2:"T", 3:"P0", 4:"P1", 5:"B0", 6:"B1", 7:"R0", 8:"R1",
             9:"A0", 10:"A1", 11:"A2", 12:"A3" ,13:"A4",14:"A5",15:"A6",16:"A7",
             17:"xx", 18:"gamma", 19:"dash"}

namestate = {"x":0,"Q":1,"T":2,"P0":3,"P1":4,"B0":5,"B1":6,"R0":7,"R1":8,
             "A0":9,"A1":10,"A2":11,"A3":12,"A4":13,"A5":14,
             "A6":15,"A7":16,"xx":17,"gamma":18,"dash":19}

Q     = 1 
T     = 2
P0    = 3
P1    = 4
B0    = 5
B1    = 6
R0    = 7
R1    = 8
A0  = 9
A1  = 10
A2  = 11
A3  = 12
A4  = 13
A5  = 14
A6  = 15
A7  = 16
xx   = 17
gamma = 18
dash  = 19

proper_states = [Q, B0, B1, R0, R1, P0, P1, A0, A1, A2, A3, A4, A5, A6, A7]

transition_csv = """
001, Q,Q,Q,Q
002, Q,Q,B0,Q
003, Q,Q,B1,Q
004, Q,Q,R0,R0
005, Q,Q,R1,Q
006, Q,Q,P0,A0
007, Q,Q,P1,A4
008, Q,Q,A0,A1
009, Q,Q,A1,A0
010, Q,Q,A4,A5
011, Q,Q,A5,A4
012, Q,Q,A2,R0
013, Q,Q,A6,Q
014, Q,Q,xx,Q
015, B0,Q,Q,Q
016, B0,Q,B0,Q
017, B0,Q,R0,R0
018, B0,Q,P1,A4
019, B0,Q,A0,A1
020, B0,Q,A5,A4
021, B0,Q,A2,R0
022, B0,Q,A6,Q
023, B1,Q,Q,Q
024, B1,Q,B1,Q
025, B1,Q,R0,R0
026, B1,Q,R1,Q
027, B1,Q,P0,A0
028, B1,Q,A1,A0
029, B1,Q,A4,A5
030, R0,Q,Q,Q
031, R0,Q,B1,Q
032, R0,Q,P0,A0
033, R0,Q,A0,A1
034, R0,Q,A1,A0
035, R0,Q,A3,Q
036, R1,Q,Q,R1
037, R1,Q,B0,R1
038, R1,Q,B1,R1
039, P0,Q,Q,A2
040, P0,Q,B1,A2
041, P0,Q,R1,A2
042, P0,Q,xx,P1
043, P1,Q,Q,A6
044, P1,Q,B0,A6
045, A0,Q,Q,R1
046, A0,Q,B0,R1
047, A1,Q,R1,Q
048, A4,Q,Q,Q
049, A4,Q,B0,Q
050, A2,Q,Q,A3
051, A2,Q,B0,A3
052, A2,Q,R1,A3
053, A2,Q,xx,P0
054, A3,Q,Q,A2
055, A3,Q,B1,A2
056, A3,Q,R1,A2
057, A3,Q,xx,P1
058, A6,Q,Q,A7
059, A6,Q,B1,A7
060, A7,Q,Q,A6
061, A7,Q,B0,A6
062, Q,     B0 , Q    , B0
063, Q,     B0 , R0   , R0
064, Q,     B0 , P0   , B0
065, Q,     B0 , P1   , B0
066, Q,     B0 , A1 , P1
067, Q,     B0 , A4 , P1
068, B1,    B0 , P0   , B0
069, B1,    B0 , P1   , B0
070, R1,    B0 , Q    , R1
071, R1,    B0 , P0   , R1
072, R1,    B0 , P1   , R1
073, P0,    B0 , Q    , B0
074, P0,    B0 , B1   , B0
075, P0,    B0 , R0   , R0
076, P0,    B0 , P0   , P0
077, P0,    B0 , P1   , P0
078, P0,    B0 , A4 , P1
079, P0,    B0 , A3 , B0
080, P1,    B0 , Q    , B0
081, P1,    B0 , B1   , B0
082, P1,    B0 , R0   , R0
083, P1,    B0 , P0   , P0
084, P1,    B0 , A4 , P1
085, A1,  B0 , P0   , B0
086, A3,  B0 , Q    , P1
087, A6,  B0 , Q    , P1
088, A6,  B0 , P0   , P1
089, A6,  B0 , P1   , P1
090,  Q,    B1, Q    ,B1
091,  Q,    B1, B0   ,B1
092,  Q,    B1, R0   ,Q
093,  Q,    B1, R1   ,B1
094,  Q,    B1, A0 ,P0
095,  Q,    B1, A5 ,P0
096,  B0,   B1, Q    ,B1
097,  B0,   B1, R0   ,Q
098,  B0,   B1, A0 ,P0
099,  B0,   B1, A5 ,P0
100,  R0,   B1, Q    ,B1
101,  R0,   B1, A0 ,P0
102,  R1,   B1, Q    ,Q
103,  R1,   B1, B0   ,Q
104,  A2, B1, Q    ,P0
105,  A2, B1, B0   ,P0
106,  A2, B1, R1   ,P0
107,  A7, B1, Q    ,P0
108,  A7, B1, B0   ,P0
109, Q,  R0, Q,    Q
110, Q,  R0, B1,   Q
111, Q,  R0, A7, Q
112, B0, R0, Q,    B1
113, B1, R0, Q,    B0
114, P0, R0, B1,   B0
115, P1, R0, B1,   B0
116, P1, R0, A7, B0
117, Q,   R1, Q,  Q
118, Q,   R1, B0, B1
119, Q,   R1, B1, B0
120, B1,  R1, Q,  Q
121, B1,  R1, P0, B0
122, B1,  R1, P1, B0
123, A5,R1, Q,  Q
124, A5,R1, P1, B0
125, Q,    P0, Q    ,P0
126, Q,    P0, P0   ,P0
127, Q,    P0, xx  ,P0
128, B0,   P0, B0   ,P0
129, B0,   P0, P0   ,P0
130, B0,   P0, xx  ,P0
131, R1,   P0, R0   ,P0
132, R1,   P0, P0   ,P0
133, R1,   P0, xx  ,P0
134, P0,   P0, Q    ,P0
135, P0,   P0, B0   ,P0
136, P0,   P0, R0   ,P0
137, P0,   P0, P0   ,T
138, P0,   P0, P1   ,T
139, P0,   P0, A2 ,P0
140, P0,   P0, xx  ,T
141, P1,   P0, P0   ,T
142, P1,   P0, P1   ,T
143, P1,   P0, xx  ,T
144, A0, P0, P0   ,P0
145, A0, P0, A2 ,P0
146, A0, P0, xx  ,P0
147, xx,  P0, Q    ,P0
148, xx,  P0, B0   ,P0
149, xx,  P0, R0   ,P0
150, xx,  P0, P0   ,T
151, xx,  P0, P1   ,T
152, xx,  P0, A2 ,P0
153, Q,    P1, Q,    P1
154, Q,    P1, P1,   P1
155, Q,    P1, xx,  P1
156, B0,   P1, B0,   P1
157, B0,   P1, P1,   P1
158, B0,   P1, xx,  P1
159, R1,   P1, R0,   P1
160, R1,   P1, P1,   P1
161, R1,   P1, xx,  P1
162, P0,   P1, P0,   T
163, P0,   P1, P1,   T
164, P0,   P1, xx,  T
165, P1,   P1, Q,    P1
166, P1,   P1, B0,   P1
167, P1,   P1, R0,   P1
168, P1,   P1, P0,   T
169, P1,   P1, P1,   T
170, P1,   P1, A6, P1
171, P1,   P1, xx,  T
172, A4, P1, P1,   P1
173, A4, P1, A6, P1
174, A4, P1, xx,  P1
175, Q,  A0, Q,  Q
176, Q,  A0, P0, B0
177, B1, A0, Q,  Q
178, B1, A0, P0, B0
179, Q,  A1, Q,  Q
180, Q,  A1, B0, Q
181, B0, A1, Q,  Q
182, B0, A1, B0, Q
183, Q,  A4, Q,  R1
184, Q,  A4, P1, R1
185, B0, A4, Q,  P1
186, B0, A4, P1, P1
187, Q,  A5, R1, Q
188, B1, A5, R1, P0
189, Q,  A2, Q,  Q
190, Q,  A2, B1, Q
191, P0, A2, Q,  B0
192, P0, A2, B1, B0
193, Q,  A3, Q,  Q
194, Q,  A3, B0, Q
195, B0, A3, Q,  Q
196, B0, A3, B0, Q
197, Q,  A6, Q,  R0
198, Q,  A6, B0, P1
199, P1, A6, Q,  R0
200, P1, A6, B0, P1
201, R0, A7, Q,  Q
202, R0, A7, B1, P0
"""

data_rows = transition_csv.strip().split('\n')

# A class to build a table from right, left, state, nextstate inputs.

class thing_table():
    def __init__(self,state):
        self.horizontal = ["Q","T","P0","P1","B0","B1","R0","R1",
             "A0","A1","A2","A3","A4","A5",
             "A6","A7","xx"]
        self.vertical = ["Q","T", "P0","P1","B0","B1","R0","R1",
             "A0","A1","A2","A3","A4","A5",
             "A6","A7","xx"]

        self.state = state
        self.body = list()
        for _ in range(18):
            self.body.append(["","","","","","","","","","","","","","","","","",""])
    
    def add_entry(self,left,right,next_state):
        y = left
        x = right
        self.body[y][x] = statename[next_state]
    
    def row_notempty(self,y):
        empty=True
        for i in range(17):
            if self.body[y][i+1] != "":
                empty=False
        return (not empty)

    def column_notempty(self,x):
        empty=True
        for y in range(17):
            if self.body[y+1][x+1] != "":
                empty=False
        return (not empty)

    def print_body(self,of,fulltable=False):
        print(f"State {statename[self.state]} Table",file=of)
        # top row
        print("   ",end="",file=of)
        count = 0
        for x,thing in enumerate(self.horizontal):
            if self.column_notempty(x) or fulltable:
                print(f"{thing.ljust(3)}", end="",file=of)
                count = count+ 1
            #else:
            #    print(f"{thing.lower().ljust(3)}", end="")
            #    count = count+ 1
        print(file=of)

        print("  "+"-"*(3*count),file=of)
    
        #rows
        for y in range(17):
            if self.row_notempty(y+1) or fulltable:
                print(f"{self.vertical[y].ljust(2)}|",end="",file=of) # left key
                for x in range(17):
                    if self.column_notempty(x) or fulltable:
                        print(f"{self.body[y+1][x+1].ljust(3)}",end="",file=of)
                    #else:
                    #    print(f"{self.body[y+1][x+1].lower().ljust(3)}",end="")



                print(file=of)
        print(file=of)

    def print_sverilog(self,of):
        print(f"// next state for {statename[self.state]} state",file=of)
        print("always_comb",file=of)
        print("begin",file=of)
        print("    case (lr)",file=of)
        for y in range(17):
            if self.row_notempty(y+1):
                for x in range(17):
                    if (self.body[y+1][x+1]!=""):
                        print(f"        {{ {self.vertical[y].ljust(2)},{self.horizontal[x]} }}: next_{statename[self.state].lower()} = {self.body[y+1][x+1].ljust(2)};",file=of)
        print(f"        default : next_{statename[self.state].lower()} = Q;",file=of)
        print("    endcase",file=of)
        print("end //always_comb,file=of")


def process_csv(filename=""):
    if filename == "":
        input_file = StringIO(transition_csv)
    else:
        input_file = open(filename,'r')

    csvreader = csv.reader(input_file, delimiter=',')

    # Need to make this read the number of states and state names
    # and do this in a loop
    q_view = thing_table(Q)
    b0_view = thing_table(B0)
    b1_view = thing_table(B1)
    p0_view = thing_table(P0)
    p1_view = thing_table(P1)
    r0_view = thing_table(R0)
    r1_view = thing_table(R1)
    a0_view = thing_table(A0)
    a1_view = thing_table(A1)
    a2_view = thing_table(A2)
    a3_view = thing_table(A3)
    a4_view = thing_table(A4)
    a5_view = thing_table(A5)
    a6_view = thing_table(A6)
    a7_view = thing_table(A7)


    for row in csvreader:
        if len(row)==5:
            linet, leftt, statet, rightt, nextstatet = row
            line = int(linet)
            left = namestate[leftt.strip()]
            state = namestate[statet.strip()]
            right = namestate[rightt.strip()]
            
            #print(f"line:_{linet}_  left.strip:_{leftt.strip()}_ rightstrip:_{rightt.strip()}_")
            nextstate = namestate[nextstatet.strip()]
            #print(f"line:{line}  left:{left}  right:{right}  state:{state}  nextstate:{nextstate}")
            
            
        
            if state == Q:
                q_view.add_entry(left,right,nextstate)
            elif state == R0:
                r0_view.add_entry(left,right,nextstate)
            elif state == R1:
                r1_view.add_entry(left,right,nextstate)
            elif state == P0:
                p0_view.add_entry(left,right,nextstate)
            elif state == P1:
                p1_view.add_entry(left,right,nextstate)
            elif state == B0:
                b0_view.add_entry(left,right,nextstate)
            elif state == B1:
                b1_view.add_entry(left,right,nextstate)
            elif state == A0:
                a0_view.add_entry(left,right,nextstate)
            elif state == A1:
                a1_view.add_entry(left,right,nextstate)
            elif state == A2:
                a2_view.add_entry(left,right,nextstate)
            elif state == A3:
                a3_view.add_entry(left,right,nextstate)
            elif state == A4:
                a4_view.add_entry(left,right,nextstate)
            elif state == A5:
                a5_view.add_entry(left,right,nextstate)
            elif state == A6:
                a6_view.add_entry(left,right,nextstate)
            elif state == A7:
                a7_view.add_entry(left,right,nextstate)
    views = (q_view, r0_view, r1_view, p0_view, p1_view, b0_view, b1_view, a0_view, a1_view, a2_view, a3_view, a4_view, a5_view, a6_view, a7_view)

    return views

def process_csv_for_run(n):
    data_rows = transition_csv.strip().split('\n')

    q_table = dict()
    r0_table = dict()
    r1_table = dict()
    b0_table = dict()
    b1_table = dict()
    p0_table = dict()
    p1_table = dict()
    a0_table = dict()
    a1_table = dict()
    a2_table = dict()
    a3_table = dict()
    a4_table = dict()
    a5_table = dict()
    a6_table = dict()
    a7_table = dict()

    input_file = StringIO(transition_csv)
    csvreader = csv.reader(input_file, delimiter=',')

    for row in csvreader:
        #print("row",row)
        if len(row)==5:
            linet, leftt, statet, rightt, nextstatet = row
            line = int(linet)
            left = namestate[leftt.strip()]
            state = namestate[statet.strip()]
            right = namestate[rightt.strip()]
            
            #print(f"line:_{linet}_  left.strip:_{leftt.strip()}_ rightstrip:_{rightt.strip()}_")
            nextstate = namestate[nextstatet.strip()]
            #print(f"line:{line}  left:{left}  right:{right}  state:{state}  nextstate:{nextstate}")
            
            prior = (left*32)+right
        
            if state == Q:
                q_table[prior] = nextstate
            elif state == R0:
                r0_table[prior] = nextstate
            elif state == R1:
                r1_table[prior] = nextstate
            elif state == P0:
                p0_table[prior] = nextstate
            elif state == P1:
                p1_table[prior] = nextstate
            elif state == B0:
                b0_table[prior] = nextstate
            elif state == B1:
                b1_table[prior] = nextstate
            elif state == A0:
                a0_table[prior] = nextstate
            elif state == A1:
                a1_table[prior] = nextstate
            elif state == A2:
                a2_table[prior] = nextstate
            elif state == A3:
                a3_table[prior] = nextstate
            elif state == A4:
                a4_table[prior] = nextstate
            elif state == A5:
                a5_table[prior] = nextstate
            elif state == A6:
                a6_table[prior] = nextstate
            elif state == A7:
                a7_table[prior] = nextstate
    tables = (q_table, r0_table, r1_table, p0_table, p1_table, b0_table, b1_table, a0_table, a1_table, a2_table, a3_table, a4_table, a5_table, a6_table, a7_table)
    return tables

def print_tables(views,of,fulltable):
    (q_view, r0_view, r1_view, p0_view, p1_view, b0_view, b1_view, a0_view, a1_view, a2_view, a3_view, a4_view, a5_view, a6_view, a7_view) = views

    q_view.print_body(of,fulltable)
    b0_view.print_body(of,fulltable)
    b1_view.print_body(of,fulltable)
    r0_view.print_body(of,fulltable)
    r1_view.print_body(of,fulltable)
    p0_view.print_body(of,fulltable)
    p1_view.print_body(of,fulltable)
    a0_view.print_body(of,fulltable)
    a1_view.print_body(of,fulltable)
    a2_view.print_body(of,fulltable)
    a3_view.print_body(of,fulltable)
    a4_view.print_body(of,fulltable)
    a5_view.print_body(of,fulltable)
    a6_view.print_body(of,fulltable)
    a7_view.print_body(of,fulltable)

def print_promela(of):
    input_file = StringIO(transition_csv)
    csvreader = csv.reader(input_file, delimiter=',')
        
    for row in csvreader:
        if len(row)==5:
            linet, leftt, statet, rightt, nextstatet = row
            line = int(linet)
            left = namestate[leftt.strip()]
            state = namestate[statet.strip()]
            right = namestate[rightt.strip()]
            nextstate = namestate[nextstatet.strip()]

            print(f"        :: ((leftstate=={leftt.strip().lower()}) && (state[n] == {statet.strip().lower()}) && (rightstate=={rightt.strip().lower()})) -> state[n] = {nextstatet.strip().lower()};",file=of)


def make_sverilog_module(views,of):
    (q_view, r0_view, r1_view, p0_view, p1_view, b0_view, b1_view, a0_view, a1_view, a2_view, a3_view, a4_view, a5_view, a6_view, a7_view) = views
    print("typedef enum logic[4:0] {q=1, r0, r1, s0, s1, b0, b1, a0, a1, a2, a3, a4, a5, a6, a7} t_state;",file=of)
    print()
    print("module wakesman_fsp_nextstate(",file=of)
    print("              input  t_state left,",file=of)
    print("              input  t_state right,",file=of)
    print("              input  t_state state,",file=of)
    print("              output t_state next_state);",file=of)
    print()

    print("logic[9:0] lr;",file=of)
    print("t_state next_q;",file=of)
    print("t_state next_p0;",file=of)
    print("t_state next_p1;",file=of)
    print("t_state next_b0;",file=of)
    print("t_state next_b1;",file=of)
    print("t_state next_r0;",file=of)
    print("t_state next_r1;",file=of)
    print("t_state next_a0;",file=of)
    print("t_state next_a1;",file=of)
    print("t_state next_a2;",file=of)
    print("t_state next_a3;",file=of)
    print("t_state next_a4;",file=of)
    print("t_state next_a5;",file=of)
    print("t_state next_a6;",file=of)
    print("t_state next_a7;",file=of)
    print(file=of)
    print("always_comb lr={left,right}",file=of)
    print(file=of)
    q_view.print_sverilog(of)
    b0_view.print_sverilog(of)
    b1_view.print_sverilog(of)
    r0_view.print_sverilog(of)
    r1_view.print_sverilog(of)
    p0_view.print_sverilog(of)
    p1_view.print_sverilog(of)
    a0_view.print_sverilog(of)
    a1_view.print_sverilog(of)
    a2_view.print_sverilog(of)
    a3_view.print_sverilog(of)
    a4_view.print_sverilog(of)
    a5_view.print_sverilog(of)
    a6_view.print_sverilog(of)
    a7_view.print_sverilog(of)

    print(file=of)
    print("always_comb",file=of)
    print("begin",file=of)
    print("    case(state,file=of)")
    print("    q  : next_state = next_q;",file=of)
    print("    r0 : next_state = next_r0;",file=of)
    print("    r1 : next_state = next_r1;",file=of)
    print("    b0 : next_state = next_b0;",file=of)
    print("    b1 : next_state = next_b1;",file=of)
    print("    p0 : next_state = next_p0;",file=of)
    print("    p1 : next_state = next_p1;",file=of)
    print("    a0 : next_state = next_a0;",file=of)
    print("    a1 : next_state = next_a1;",file=of)
    print("    a2 : next_state = next_a2;",file=of)
    print("    a3 : next_state = next_a3;",file=of)
    print("    a4 : next_state = next_a4;",file=of)
    print("    a5 : next_state = next_a5;",file=of)
    print("    a6 : next_state = next_a6;",file=of)
    print("    a7 : next_state = next_a7;",file=of)
    print("    default : next_state = q;",file=of)
    print("    endcase",file=of)
    print("end",file=of)
    print(file=of)
    print("endmodule",file=of)

# Code to run the FSP

def leftval(state,x,n):
    return state[x-1]

def rightval(state,x,n):
    return state[x+1]

def printstate(row,state,of):
    print("%02d : " % row,end="",file=of)
    for i,cell in enumerate(state):
        if (i>0) and (i<(len(state)-1)):
            print("%s" % statename[cell].ljust(5),end="",file=of)
    print(file=of)
    
def runit(n,of):
    tables = process_csv_for_run(n)
    (q_table, r0_table, r1_table, p0_table, p1_table, b0_table, b1_table, a0_table, a1_table, a2_table, a3_table, a4_table, a5_table, a6_table, a7_table)=tables

    state = [Q for _ in range(n+2)]
    next_state = [Q for _ in range(n+2)]

    state[0]=xx
    state[1]=P0
    state[n+1]=xx
    next_state[0]=xx
    next_state[n+1]=xx

    printstate(0,state,of)

    for i in range((2*n)-2):
        for position,cell in enumerate(state[:-1]):
            if (position > 0):
                left = state[position-1]
                right = state[position+1]
                prior = (left*32)+right
            if cell == xx:
                next_state[position]=xx
            elif cell == Q:
                next_state[position] = q_table[prior]
            elif cell == B0:
                next_state[position] = b0_table[prior]
            elif cell == B1:
                next_state[position] = b1_table[prior]
            elif cell == P0:
                next_state[position] = p0_table[prior]
            elif cell == P1:
                next_state[position] = p1_table[prior]
            elif cell == R0:
                next_state[position] = r0_table[prior]
            elif cell == R1:
                next_state[position] = r1_table[prior]
            elif cell == A0:
                next_state[position] = a0_table[prior]
            elif cell == A1:
                next_state[position] = a1_table[prior]
            elif cell == A2:
                next_state[position] = a2_table[prior]
            elif cell == A3:
                next_state[position] = a3_table[prior]
            elif cell == A4:
                next_state[position] = a4_table[prior]
            elif cell == A5:
                next_state[position] = a5_table[prior]
            elif cell == A6:
                next_state[position] = a6_table[prior]
            elif cell == A7:
                next_state[position] = a7_table[prior]
            elif cell == T:
                next_state[position] = T
            else:
                raise Exception("Unexpected state: %s" % statename[cell])
        state = next_state[:]
        printstate(i+1,state,of)

if __name__=="__main__":
    #Handle the command line options
    parser = OptionParser()
    parser.add_option("-f", "--file", dest="filename",
                      help="Write output to <filename> instead of stdout", metavar="FILE")
    parser.add_option("-q", "--quiet",
                      action="store_true", dest="quiet", default=False,
                      help="Don't print status messages to stdout")
    parser.add_option("-v", "--verbose",
                      action="store_true", dest="verbose", default=False,
                      help="Show many internal gory details")
    parser.add_option("-s", "--sverilog", action="store_true", dest="sverilog",default=False, help="Output system verilog module for next state calculation")
    parser.add_option("-t", "--tables", action="store_true", dest="tables",default=False, help="Output tables for the next state calculation")
    parser.add_option("-T", "--fulltable", action="store_true", dest="fulltable",default=False, help="Show full next state grid, including empty rows and columns")
    parser.add_option("-r", "--run", dest="run",
                      help="Run FSP with <width> soldiers", metavar="WIDTH")
    parser.add_option("-p", "--promela", action="store_true", dest="promela",default=False, help="Output promela model for the FSP")

    (options, args) = parser.parse_args()

    if (options.filename==None):
        use_output_file = False
        output_filename = ""
    else:
        use_output_file = True
        output_filename = options.filename

    fulltable = options.fulltable

    # Output either goes to a file or stdout
    if (use_output_file):
        of = open(output_filename,'w')
    else:
        of = sys.stdout

    # Makes the FSP tables from the CSV
    views = process_csv()

    if (options.tables) == True or (fulltable):
        print_tables(views,of,fulltable)

    if options.sverilog == True:
        make_sverilog_module(views,of)

    if options.run!=None:
        width = int(options.run)
        runit(width,of)

    if options.promela == True:
        print_promela(of)


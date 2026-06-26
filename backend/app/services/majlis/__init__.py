"""Majlis room-type engine (Saudi formal reception room).

A SEPARATE placement engine from the family living-room engine: seating lines every
wall (perimeter), all facing the open centre, filled until the walls are full. This
package only READS the shared spatial primitives (services/spatial/*) - it never
mutates the cached RoomAnalysis nor the family plan cache. See the phased plan; P0 is
the routing scaffold (stub plan), the real perimeter-fill engine lands in P1.
"""

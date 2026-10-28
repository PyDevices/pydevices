# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Find the touch_rotation_table for a board's touch screen, then draw.

Asks you to touch a box in each corner of the screen. From where the touch
screen says those four touches landed, it works out how the touch screen's
axes line up with the display, and prints the touch_rotation_table to put in
board_config.py: one entry for each of the display's four rotations. It
reads the corners with the table set to zeros, so what it finds doesn't
depend on the table you have now, and it tells you whether yours matches. The
display never has to rotate, so it works on displays that can't.

Then touch anywhere: it draws a dot where you touch, placed with the table
it found, so you can see the table is right.

Needs: a board_config with a display_drv and a touch_read, which a PyDevices
board package provides, and pygraphics.

Run it:
    mpremote run appdev_touch_calibrate.py

Tested on: not yet.
"""

import board_config
from board_config import display_drv
from pygraphics import round_rect, text16

import appdev

# Read the touch screen as it is, with no rotation applied.
app = appdev.App(board_config, touch_rotation_table=(0, 0, 0, 0))

# Change these to match your setup.
FG_COLOR = -1  # white
BG_COLOR = 0  # black
DOT = 4  # the size of the dots you draw once it's done

# What each bit of a touch_rotation_table entry does, in this order: swap x
# and y, then count x from the right, then count y from the bottom.
SWAP_XY = 0b001
REVERSE_X = 0b010
REVERSE_Y = 0b100

# How each of the four rotations turns the display's coordinates, written
# the same way. It's the table a touch screen lined up with the display
# needs.
TURNS = (0b000, 0b101, 0b110, 0b011)

LABEL = "Touch here"
CORNERS = ((0, 0), (1, 0), (0, 1), (1, 1))  # top left, top right, bottom left, bottom right


def to_matrix(mask):
    """A table entry as the 2x2 matrix that turns (x, y) into the display's."""
    matrix = [[0, 1], [1, 0]] if mask & SWAP_XY else [[1, 0], [0, 1]]
    if mask & REVERSE_X:
        matrix[0] = [-v for v in matrix[0]]
    if mask & REVERSE_Y:
        matrix[1] = [-v for v in matrix[1]]
    return matrix


def to_mask(matrix):
    """The table entry for a matrix made by to_matrix."""
    mask = SWAP_XY if matrix[0][0] == 0 else 0
    if sum(matrix[0]) < 0:
        mask |= REVERSE_X
    if sum(matrix[1]) < 0:
        mask |= REVERSE_Y
    return mask


def multiply(a, b):
    return [[a[i][0] * b[0][j] + a[i][1] * b[1][j] for j in range(2)] for i in range(2)]


def mask_from(touches):
    """The table entry that puts these four corner touches where they belong."""
    top_left, top_right, bottom_left, bottom_right = touches
    # Which way the touch screen's numbers move going across the display, and
    # going down it.
    across = [top_right[i] - top_left[i] + bottom_right[i] - bottom_left[i] for i in (0, 1)]
    down = [bottom_left[i] - top_left[i] + bottom_right[i] - top_right[i] for i in (0, 1)]
    swap = abs(across[1]) > abs(across[0])
    if swap != (abs(down[0]) > abs(down[1])):
        return None  # across and down moved the same way: the touches were off
    mask = SWAP_XY if swap else 0
    if (across[1] if swap else across[0]) < 0:
        mask |= REVERSE_X
    if (down[0] if swap else down[1]) < 0:
        mask |= REVERSE_Y
    return mask


def table_from(mask):
    """The whole table, from the entry for the display's current rotation."""
    turn = to_matrix(TURNS[getattr(display_drv, "rotation", 0) // 90 % 4])
    # Undo the current rotation's turn (a turn's inverse is its transpose),
    # then add each rotation's own.
    unturned = [[turn[j][i] for j in range(2)] for i in range(2)]
    upright = multiply(unturned, to_matrix(mask))
    return tuple(to_mask(multiply(to_matrix(t), upright)) for t in TURNS)


def place(point, mask):
    """Where a touch lands on the display with this table entry."""
    x, y = point
    if mask & SWAP_XY:
        x, y = y, x
    if mask & REVERSE_X:
        x = display_drv.width - x - 1
    if mask & REVERSE_Y:
        y = display_drv.height - y - 1
    return x, y


def draw_target(corner, color):
    """Draw the box in one corner, or clear it with the background color."""
    half_width, half_height = display_drv.width // 2, display_drv.height // 2
    x, y = corner[0] * half_width, corner[1] * half_height
    round_rect(display_drv, x + 10, y + 10, half_width - 20, half_height - 20, 10, color, True)
    if color != BG_COLOR:
        text16(
            display_drv,
            LABEL,
            x + (half_width - len(LABEL) * 8) // 2,
            y + (half_height - 16) // 2,
            BG_COLOR,
        )
    display_drv.show()


touches = []
found = []  # the table entry for the current rotation, once it's known


def start():
    touches.clear()
    display_drv.fill(BG_COLOR)
    print("Touch the box in each corner.")
    draw_target(CORNERS[0], FG_COLOR)


def finish():
    mask = mask_from(touches)
    if mask is None:
        print("Those touches didn't make a rectangle. Starting over.\n")
        start()
        return
    found.append(mask)
    table = table_from(mask)
    line = "touch_rotation_table = %s" % (table,)
    # Compare with the table board_config.py has now.
    current = tuple(getattr(board_config, "touch_rotation_table", None) or TURNS)
    if current == table:
        print("board_config.py already has the right table:\n    " + line)
    else:
        print("board_config.py has %s. Change it to:\n    %s" % (current, line))
    print("Now touch anywhere to draw.")
    display_drv.fill(BG_COLOR)
    text16(display_drv, line, (display_drv.width - len(line) * 8) // 2, 8, FG_COLOR)
    display_drv.show()


# Record a touch in each corner; once all four are in, draw dots instead.
def on_touch(event):
    if found:
        x, y = place(event.pos, found[0])
        display_drv.fill_rect(x - DOT // 2, y - DOT // 2, DOT, DOT, FG_COLOR)
        display_drv.show()
        return
    if event.type != app.events.MOUSEBUTTONDOWN:
        return
    touches.append(event.pos)
    print("Corner %d: the touch screen says %s" % (len(touches), event.pos))
    draw_target(CORNERS[len(touches) - 1], BG_COLOR)
    if len(touches) < len(CORNERS):
        draw_target(CORNERS[len(touches)], FG_COLOR)
    else:
        finish()


app.on(app.events.MOUSEBUTTONDOWN, on_touch)
app.on(app.events.MOUSEMOTION, on_touch)
start()

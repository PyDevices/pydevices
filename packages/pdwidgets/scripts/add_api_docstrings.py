"""One-shot helper to add Google-style API docstrings (run manually if needed)."""

from __future__ import annotations

import ast
import pathlib
import textwrap

from _repo_paths import PDWIDGETS_DIR

ROOT = PDWIDGETS_DIR

CLASS_DOCS = {
    "Widget": "Base class for all pdwidgets UI elements.",
    "Display": "Root display surface that owns the framebuffer, event loop, and widget tree.",
    "Screen": "Full-screen container for a page of widgets.",
    "Task": "Repeating callback scheduled by :class:`Display`.",
    "Console": "Framebuffer text console with optional vertical scrolling.",
    "Accordion": "Stack of titled expansion panels; ``exclusive`` keeps at most one open.",
    "AppBar": "Top title bar with optional leading back button.",
    "Badge": "Small status dot or rounded count pill.",
    "BottomSheet": "Modal slide-up panel with scrim tap-to-dismiss.",
    "Button": "Clickable control with optional icon and text label.",
    "Card": "Rounded container with optional title and drop shadow.",
    "Chart": "Lightweight line or bar chart for numeric sequences.",
    "CheckBox": "Boolean toggle rendered as checked/unchecked icons.",
    "Chip": "Compact selectable filter chip.",
    "ColorPicker": "RGB565 color picker with hue strip and saturation/value region.",
    "Column": "Vertical layout container that stacks children top-to-bottom.",
    "DatePicker": "Month calendar for selecting a date.",
    "Dialog": "Modal message box with title, body, and action buttons.",
    "DigitalClock": "Live-updating HH:MM:SS clock label.",
    "Divider": "Thin horizontal rule for separating sections.",
    "Drawer": "Modal side panel that slides in from the left or right.",
    "Dropdown": "Header button that opens a modal list of options.",
    "Form": "Non-visual binder for named form fields and validation.",
    "FormRow": "Horizontal row with a left label and trailing control.",
    "Gauge": "Arc gauge displaying a normalized value in ``[0, 1]``.",
    "Grid": "Fixed-column grid layout container.",
    "Icon": "Monochrome or BMP565 icon display.",
    "IconButton": "Button whose content is a centered icon.",
    "Image": "Raster image widget (``.pbm`` or BMP565 ``.bmp``).",
    "Keyboard": "On-screen QWERTY keyboard for focused text fields.",
    "Label": "Text display using romfont or an optional proportional font.",
    "ListView": "Vertically scrollable list container.",
    "Menu": "Modal popup action menu of labeled callbacks.",
    "Navigator": "Page stack with push, pop, and replace navigation.",
    "NumberStepper": "Bounded numeric stepper with ``-`` / ``+`` buttons.",
    "Page": "Full-bleed content page for :class:`Navigator` or :class:`TabView`.",
    "PasswordField": "Single-line password entry with masked glyphs.",
    "PinPad": "3×4 numeric keypad for PIN or code entry.",
    "ProgressBar": "Horizontal or vertical progress indicator (0–1).",
    "RadioButton": "Mutually exclusive checked icon; belongs to a :class:`RadioGroup`.",
    "RadioGroup": "Invisible coordinator that enforces single radio selection.",
    "Row": "Horizontal layout container that stacks children left-to-right.",
    "ScrollBar": "Scroll control with end arrows and a central slider.",
    "ScrollView": "Clipped scrollable viewport with drag, wheel, and scrollbar.",
    "SegmentedControl": "Exclusive pill-style segment selector.",
    "Slider": "Draggable 0–1 value control with a circular knob.",
    "Spinner": "Animated circular busy indicator.",
    "Switch": "Pill track with sliding knob for boolean on/off.",
    "TabView": "Tab bar plus content area with one :class:`Page` per tab.",
    "TextBox": "Read-only formatted text display.",
    "TextInput": "Single-line editable text field with focus management.",
    "Toast": "Transient bottom banner that auto-hides after a duration.",
    "Toggle": "Icon button that toggles between on and off states.",
    "ToggleButton": "Pre-themed :class:`Toggle` using standard on/off icons.",
}

MODULE_DOCS = {
    "widget.py": "Base widget class and geometry/event primitives.",
    "display.py": "Display framebuffer, rendering, and app integration.",
    "screen.py": "Full-screen widget container.",
    "task.py": "Scheduled repeating tasks for :class:`Display`.",
    "console.py": "Framebuffer text console widget.",
    "button.py": "Button widget with optional icon and label.",
    "label.py": "Text label widget.",
    "text_box.py": "Read-only formatted text display.",
    "digital_clock.py": "Live digital clock label.",
    "tab_view.py": "Tab bar with per-tab content pages.",
    "progress_bar.py": "Progress bar widget.",
    "image.py": "Raster image widget.",
    "app_bar.py": "Application title bar.",
    "badge.py": "Status badge widget.",
    "card.py": "Card container widget.",
    "check_box.py": "Checkbox toggle widget.",
    "column.py": "Vertical layout container.",
    "dialog.py": "Modal dialog widget.",
    "divider.py": "Horizontal divider widget.",
    "dropdown.py": "Dropdown selection widget.",
    "form.py": "Form field binder and validation.",
    "form_row.py": "Label plus control form row.",
    "gauge.py": "Arc gauge widget.",
    "icon.py": "Icon display widget.",
    "icon_button.py": "Icon-only button.",
    "keyboard.py": "On-screen keyboard widget.",
    "list_view.py": "Scrollable list container.",
    "navigator.py": "Page stack navigator.",
    "number_stepper.py": "Numeric stepper widget.",
    "page.py": "Navigator/tab content page.",
    "radio_button.py": "Radio button widget.",
    "radio_group.py": "Radio button group coordinator.",
    "row.py": "Horizontal layout container.",
    "scroll_bar.py": "Scrollbar widget.",
    "slider.py": "Slider widget.",
    "spinner.py": "Busy spinner widget.",
    "switch.py": "On/off switch widget.",
    "text_input.py": "Single-line text input field.",
    "toast.py": "Transient toast notification.",
    "toggle.py": "Icon toggle base class.",
    "toggle_button.py": "Standard on/off toggle button.",
}

METHOD_DOCS = {
    ("Widget", "parent", "get"): "Parent widget that contains this widget.",
    ("Widget", "parent", "set"): (
        "Reparent this widget.\n\n"
        "Args:\n"
        "    parent (Widget): New parent, or ``None`` to detach."
    ),
    ("Widget", "padded_area", "get"): "Bounding box inset by :attr:`padding`.",
    ("Widget", "x", "get"): "Absolute x-coordinate after :attr:`align` is applied.",
    ("Widget", "x", "set"): "Set the relative x-coordinate (triggers relayout).",
    ("Widget", "y", "get"): "Absolute y-coordinate after :attr:`align` is applied.",
    ("Widget", "y", "set"): "Set the relative y-coordinate (triggers relayout).",
    ("Widget", "width", "get"): "Widget width in pixels.",
    ("Widget", "width", "set"): "Set widget width in pixels.",
    ("Widget", "height", "get"): "Widget height in pixels.",
    ("Widget", "height", "set"): "Set widget height in pixels.",
    ("Widget", "align", "get"): "Alignment constant from :data:`ALIGN`.",
    ("Widget", "align", "set"): "Set alignment relative to :attr:`align_to`.",
    ("Widget", "align_to", "get"): "Widget used as the alignment anchor.",
    ("Widget", "align_to", "set"): "Set the alignment anchor widget.",
    ("Widget", "display", "get"): "Root :class:`Display` for this widget subtree.",
    ("Widget", "color_theme", "get"): "Semantic color palette from the display.",
    ("Widget", "value", "get"): "Widget value (text, number, bool, etc.).",
    ("Widget", "value", "set"): "Set the value and call :meth:`changed` when it differs.",
    ("Widget", "add_dirty_widget", "func"): "Mark a direct child as dirty for rendering.",
    ("Widget", "add_dirty_descendant", "func"): "Bubble a dirty descendant up the tree.",
    ("Widget", "remove_dirty_widget", "func"): "Clear a child from the dirty set.",
    ("Widget", "remove_dirty_descendant", "func"): "Clear a descendant branch from the dirty set.",
    ("Display", "parent", "get"): "Always ``None``; the display is the root.",
    ("Display", "parent", "set"): "Raise :exc:`ValueError` if a parent is assigned.",
    ("Display", "x", "get"): "Display x offset (always 0).",
    ("Display", "y", "get"): "Display y offset (always 0).",
    ("Display", "width", "get"): "Framebuffer width in pixels.",
    ("Display", "height", "get"): "Framebuffer height in pixels.",
    ("Display", "display", "get"): "Return ``self``.",
    ("Display", "color_theme", "get"): "Semantic color theme for this display.",
    ("Display", "visible", "get"): "Always ``True``.",
    ("Display", "visible", "set"): "Raise :exc:`ValueError`; the display cannot be hidden.",
    ("Display", "active_screen", "get"): "The currently attached :class:`Screen`, if any.",
    ("Display", "active_screen", "set"): "Replace the active screen (removes any previous screen).",
    ("Display", "add_child", "func"): "Set :attr:`active_screen` to ``screen``.",
    ("Display", "set_position", "func"): "Reset geometry to the full display size.",
    ("Console", "clear", "func"): "Erase the console and reset the text cursor.",
    ("Console", "readinto", "func"): (
        "Read bytes into ``buf`` (``io.IOBase`` interface).\n\n"
        "Args:\n"
        "    buf (bytearray): Destination buffer.\n"
        "    nbytes (int): Maximum bytes to read.\n\n"
        "Returns:\n"
        "    int | None: Number of bytes read, or ``None`` if no reader is set."
    ),
    ("Console", "write", "func"): (
        "Write text to the console (``io.IOBase`` interface).\n\n"
        "Args:\n"
        "    buf (bytes | str): Text or bytes to render.\n"
        "    fg (int | None): Foreground color override.\n"
        "    bg (int | None): Background color override.\n\n"
        "Returns:\n"
        "    int: Number of bytes written."
    ),
    ("Console", "draw", "func"): "Flush accumulated dirty console regions to the display.",
    ("Button", "press", "func"): "Draw pressed-state outline (mouse down handler).",
    ("Button", "release", "func"): "Restore normal outline (mouse up handler).",
    ("Label", "char_width", "get"): "Rendered character width in pixels.",
    ("Label", "char_height", "get"): "Rendered character height in pixels.",
    ("TextBox", "char_width", "get"): "Rendered character width in pixels.",
    ("TextBox", "char_height", "get"): "Rendered character height in pixels.",
    ("BottomSheet", "show", "func"): "Show the sheet, grab modal capture, and redraw.",
    ("BottomSheet", "hide_sheet", "func"): "Hide the sheet, release modal capture, and call ``on_dismiss``.",
    ("BottomSheet", "draw", "func"): "Fill the scrim behind the slide-up panel.",
    ("Drawer", "content", "get"): "The :class:`Card` panel; add child widgets here.",
    ("Drawer", "show", "func"): "Show the drawer, grab modal capture, and redraw.",
    ("Drawer", "hide_drawer", "func"): "Hide the drawer, release modal capture, and call ``on_dismiss``.",
    ("Drawer", "draw", "func"): "Fill the scrim behind the side panel.",
    ("Menu", "show", "func"): "Show the menu, grab modal capture, and redraw.",
    ("Menu", "hide_menu", "func"): "Hide the menu and release modal capture.",
    ("Menu", "draw", "func"): "Fill the scrim behind the popup menu.",
    ("ScrollView", "scroll_y", "get"): "Current vertical scroll offset in pixels.",
    ("ScrollView", "scroll_y", "set"): "Set vertical scroll offset, clamped to content bounds.",
    ("ScrollView", "set_content_height", "func"): (
        "Update total scrollable content height.\n\n"
        "Args:\n"
        "    h (int): Content height in pixels (at least viewport height)."
    ),
    ("ScrollView", "add_child", "func"): "Add a child and expand content height if needed.",
    ("ScrollView", "draw", "func"): "Draw the viewport background.",
    ("Grid", "add_child", "func"): "Add a child at the next grid cell.",
    ("Grid", "remove_child", "func"): "Remove a child and reflow remaining cells.",
    ("Chart", "draw", "func"): "Draw the chart axes and data series.",
    ("Chip", "draw", "func"): "Draw the chip background and label.",
    ("ColorPicker", "draw", "func"): "Draw the hue strip and saturation/value region.",
    ("DatePicker", "draw", "func"): "Draw the month header and day grid.",
    ("DigitalClock", "update_time", "func"): "Refresh the displayed time from the system clock.",
    ("Image", "changed", "func"): "Invalidate after the image path changes.",
    ("ProgressBar", "changed", "func"): "Invalidate after the progress value changes.",
    ("SegmentedControl", "draw", "func"): "Draw segment backgrounds and labels.",
    ("TabView", "index", "get"): "Index of the currently selected tab.",
    ("TabView", "index", "set"): "Select the tab at ``index`` (alias for :meth:`set_index`).",
    ("TabView", "pages", "get"): "List of :class:`Page` widgets, one per tab.",
    ("Form", "__init__", "func"): (
        "Register named fields for validation and value collection.\n\n"
        "Args:\n"
        "    on_commit (callable | None): Called as ``on_commit(form)`` on successful commit.\n"
        "    error_label (Label | None): Label that receives validation error text."
    ),
}

SKIP_METHODS = {
    ("Widget", "__init__"),
    ("Display", "__init__"),
    ("Screen", "__init__"),
    ("Task", "__init__"),
    ("Console", "__init__"),
}


def is_public(name: str) -> bool:
    return not name.startswith("_")


def method_kind(node: ast.FunctionDef) -> str:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "property":
            return "get"
        if isinstance(dec, ast.Attribute) and dec.attr == "setter":
            return "set"
    return "func"


def format_docstring(indent: str, body: str) -> list[str]:
    body = textwrap.dedent(body).strip("\n")
    if "\n" not in body:
        end = "" if body.endswith(".") else "."
        return [indent + f'"""{body}{end}"""\n']
    lines = body.split("\n")
    out = [indent + '"""\n']
    for ln in lines:
        out.append(indent + ln + "\n")
    out.append(indent + '"""\n')
    return out


def signature_end_line(lines: list[str], start_idx: int) -> int:
    i = start_idx
    while i < len(lines):
        if lines[i].rstrip().endswith(":"):
            return i
        i += 1
    return start_idx


def has_following_docstring(lines: list[str], after_idx: int) -> bool:
    i = after_idx + 1
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines):
        return False
    return lines[i].lstrip().startswith('"""') or lines[i].lstrip().startswith("'''")


def collect_insert_line(lines: list[str], node) -> int | None:
    start = node.lineno - 1
    while start > 0 and lines[start - 1].lstrip().startswith("@"):
        start -= 1
    end = signature_end_line(lines, start)
    if has_following_docstring(lines, end):
        return None
    return end + 1


def process_file(path: pathlib.Path) -> bool:
    src = path.read_text()
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    pending: list[tuple[int, list[str]]] = []

    if not ast.get_docstring(tree) and path.name in MODULE_DOCS:
        insert_at = 0
        for i, line in enumerate(lines):
            if line.strip() and not line.startswith("#"):
                insert_at = i
                break
        pending.append((insert_at, format_docstring("", MODULE_DOCS[path.name]) + ["\n"]))

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ClassDef)
            and is_public(node.name)
            and not ast.get_docstring(node)
            and node.name in CLASS_DOCS
        ):
            at = collect_insert_line(lines, node)
            if at is not None:
                indent = "    "
                pending.append((at, format_docstring(indent, CLASS_DOCS[node.name])))

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and is_public(node.name):
            cls = node.name
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not is_public(item.name) or ast.get_docstring(item):
                    continue
                if (cls, item.name) in SKIP_METHODS:
                    continue
                doc = METHOD_DOCS.get((cls, item.name, method_kind(item)))
                if doc is None:
                    continue
                at = collect_insert_line(lines, item)
                if at is not None:
                    sig_end = at - 1
                    sig_indent = lines[sig_end][: len(lines[sig_end]) - len(lines[sig_end].lstrip())]
                    pending.append((at, format_docstring(sig_indent + "    ", doc)))

    if not pending:
        return False

    for at, chunk in sorted(pending, key=lambda x: x[0], reverse=True):
        lines[at:at] = chunk

    ast.parse("".join(lines))
    path.write_text("".join(lines))
    return True


def main() -> None:
    changed = []
    for path in sorted(ROOT.rglob("*.py")):
        if path.name.startswith("_") and path.name != "__init__.py":
            continue
        if process_file(path):
            changed.append(str(path))
    print(f"Updated {len(changed)} files")


if __name__ == "__main__":
    main()

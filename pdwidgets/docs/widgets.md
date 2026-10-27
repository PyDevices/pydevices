# Widgets

pdwidgets has 49 widgets. Reach each one as `pd.Name` after `import pdwidgets as
pd`; the module loads the first time you use it. On a board short of memory,
import the widget directly instead, such as `from pdwidgets.widgets.button import
Button`, so only the widgets you use are loaded.

Every widget takes its parent first and accepts `x`, `y`, `w`, `h`, `align`,
`align_to`, `fg`, `bg`, `visible`, `value` and `padding` as keywords, plus the
arguments of its own, documented in its docstring in
[`lib/pdwidgets`](https://github.com/PyDevices/pydevices/tree/main/pdwidgets/lib/pdwidgets). A `Label`
takes its text as `value=`, and a `Button` takes it as `label=`; neither takes
`text=`.

The tables are grouped by what the widget is for.

## Buttons and badges

| Widget | Module | What it is |
|---|---|---|
| `Button` | `pdwidgets.widgets.button` | Clickable control with optional icon and text label. |
| `IconButton` | `pdwidgets.widgets.icon_button` | Button whose content is a centered icon. |
| `ToggleButton` | `pdwidgets.widgets.toggle_button` | Pre-themed `Toggle` using standard on/off icons. |
| `Toggle` | `pdwidgets.widgets.toggle` | Icon button that toggles between on and off states. |
| `Badge` | `pdwidgets.widgets.badge` | Small status dot or rounded count pill. |
| `Chip` | `pdwidgets.widgets.chip` | Compact selectable filter chip. |
| `Divider` | `pdwidgets.widgets.divider` | Thin horizontal rule for separating sections. |
| `Icon` | `pdwidgets.widgets.icon` | Monochrome or RGB565 icon display. |
| `Image` | `pdwidgets.widgets.image` | Raster image widget (package icon module or `.pbm` / `.bmp` path). |

## Text and input

| Widget | Module | What it is |
|---|---|---|
| `Label` | `pdwidgets.widgets.label` | Text display using romfont or an optional proportional font. |
| `TextBox` | `pdwidgets.widgets.text_box` | Read-only formatted text display. |
| `TextInput` | `pdwidgets.widgets.text_input` | Single-line editable text field with focus management. |
| `PasswordField` | `pdwidgets.widgets.password_field` | Single-line password entry; drawn text is replaced with `*` masks. |
| `NumberStepper` | `pdwidgets.widgets.number_stepper` | Bounded numeric stepper with `-` / `+` buttons. |
| `Keyboard` | `pdwidgets.widgets.keyboard` | On-screen QWERTY keyboard for focused text fields. |
| `PinPad` | `pdwidgets.widgets.pin_pad` | 3×4 numeric keypad for PIN or code entry. |

## Selection and toggles

| Widget | Module | What it is |
|---|---|---|
| `Switch` | `pdwidgets.widgets.switch` | Pill track with sliding knob for boolean on/off. |
| `CheckBox` | `pdwidgets.widgets.check_box` | Boolean toggle rendered as checked/unchecked icons. |
| `RadioButton` | `pdwidgets.widgets.radio_button` | Mutually exclusive checked icon; belongs to a `RadioGroup`. |
| `RadioGroup` | `pdwidgets.widgets.radio_group` | Invisible coordinator that enforces single radio selection. |
| `SegmentedControl` | `pdwidgets.widgets.segmented_control` | Exclusive pill-style segment selector. |
| `Dropdown` | `pdwidgets.widgets.dropdown` | Header button that opens a modal list of options. |
| `Slider` | `pdwidgets.widgets.slider` | Draggable 0–1 value control with a circular knob. |
| `ColorPicker` | `pdwidgets.widgets.color_picker` | RGB565 color picker with hue strip and saturation/value region. |
| `DatePicker` | `pdwidgets.widgets.date_picker` | Month calendar for selecting a date. |

## Layout containers

| Widget | Module | What it is |
|---|---|---|
| `Card` | `pdwidgets.widgets.card` | Rounded container with optional title and drop shadow. |
| `Row` | `pdwidgets.widgets.row` | A container that lays its children out left-to-right with fixed spacing. |
| `Column` | `pdwidgets.widgets.column` | A container that stacks its children top-to-bottom with fixed spacing. |
| `Grid` | `pdwidgets.widgets.grid` | Fixed-column grid layout container. |
| `ScrollView` | `pdwidgets.widgets.scroll_view` | Clipped scrollable viewport with drag, wheel, and scrollbar. |
| `ScrollBar` | `pdwidgets.widgets.scroll_bar` | Scroll control with end arrows and a central slider. |
| `ListView` | `pdwidgets.widgets.list_view` | Vertically scrollable list container. |
| `Accordion` | `pdwidgets.widgets.accordion` | Stack of titled expansion panels; `exclusive` keeps at most one open. |
| `TabView` | `pdwidgets.widgets.tab_view` | Tab bar plus content area with one `Page` per tab. |
| `Page` | `pdwidgets.widgets.page` | Full-bleed content page for Navigator or `TabView`. |
| `Form` | `pdwidgets.widgets.form` | Register named field widgets and collect/validate their values. |
| `FormRow` | `pdwidgets.widgets.form_row` | Horizontal row with a left label and trailing control. |

## Navigation

| Widget | Module | What it is |
|---|---|---|
| `AppBar` | `pdwidgets.widgets.app_bar` | Top title bar with optional leading back button. |
| `Drawer` | `pdwidgets.widgets.drawer` | Modal side panel that slides in from the left or right. |
| `BottomSheet` | `pdwidgets.widgets.bottom_sheet` | Modal slide-up panel with scrim tap-to-dismiss. |
| `Menu` | `pdwidgets.widgets.menu` | Modal popup action menu of labeled callbacks. |
| `Navigator` | `pdwidgets.widgets.navigator` | Page stack with push, pop, and replace navigation. |

## Feedback and overlays

| Widget | Module | What it is |
|---|---|---|
| `Dialog` | `pdwidgets.widgets.dialog` | Modal message box with title, body, and action buttons. |
| `Toast` | `pdwidgets.widgets.toast` | Transient bottom banner that auto-hides after a duration. |
| `ProgressBar` | `pdwidgets.widgets.progress_bar` | Horizontal or vertical progress indicator (0–1). |
| `Spinner` | `pdwidgets.widgets.spinner` | Animated circular busy indicator. |

## Display

| Widget | Module | What it is |
|---|---|---|
| `Chart` | `pdwidgets.widgets.chart` | Lightweight line or bar chart for numeric sequences. |
| `Gauge` | `pdwidgets.widgets.gauge` | Arc gauge displaying a normalized value in `[0, 1]`. |
| `DigitalClock` | `pdwidgets.widgets.digital_clock` | Live-updating HH:MM:SS clock label. |
## The classes underneath

| Name | What it is |
|---|---|
| `Display` | Joins a display driver to an app, routes input to widgets and draws the ones that changed. |
| `Screen` | One full-display page. A `Display` shows one at a time. |
| `Widget` | The base of every widget: geometry, children, visibility, callbacks. Use it directly for a custom container. |
| `Task` | A repeating job scheduled with `display.add_task`. |
| `ColorTheme`, `IconTheme` | The color roles and the icon names widgets use. |
| `ALIGN`, `POSITION`, `pct` | Alignment flags and percentage sizes. See [Lay out widgets](guides/lay-out-widgets.md). |

from __future__ import annotations

from difflib import get_close_matches
from functools import lru_cache
from typing import cast, Iterable, NoReturn

import rich.repr

from ._error_tools import friendly_list
from ._help_renderables import HelpText
from ._help_text import (
    spacing_invalid_value,
    spacing_wrong_number_of_values,
    scalar_help_text,
    color_property_help_text,
    string_enum_help_text,
    border_property_help_text,
    layout_property_help_text,
    docks_property_help_text,
    dock_property_help_text,
    fractional_property_help_text,
    align_help_text,
    offset_property_help_text,
    offset_single_axis_help_text,
    style_flags_property_help_text,
)
from .constants import (
    VALID_ALIGN_HORIZONTAL,
    VALID_ALIGN_VERTICAL,
    VALID_BORDER,
    VALID_BOX_SIZING,
    VALID_EDGE,
    VALID_DISPLAY,
    VALID_OVERFLOW,
    VALID_VISIBILITY,
    VALID_STYLE_FLAGS,
)
from .errors import DeclarationError, StyleValueError
from .model import Declaration
from .scalar import Scalar, ScalarOffset, Unit, ScalarError, ScalarParseError
from .styles import DockGroup, Styles
from .tokenize import Token
from .transition import Transition
from .types import BoxSizing, Edge, Display, Overflow, Visibility
from ..color import Color, ColorParseError
from .._duration import _duration_as_seconds
from .._easing import EASING
from ..geometry import Spacing, SpacingDimensions, clamp


def _join_tokens(tokens: Iterable[Token], joiner: str = "") -> str:
    """Convert tokens into a string by joining their values

    Args:
        tokens (Iterable[Token]): Tokens to join
        joiner (str): String to join on, defaults to ""

    Returns:
        str: The tokens, joined together to form a string.
    """
    return joiner.join(token.value for token in tokens)


class StylesBuilder:
    """
    The StylesBuilder object takes tokens parsed from the CSS and converts
    to the appropriate internal types.
    """

    def __init__(self) -> None:
        self.styles = Styles()

    def __rich_repr__(self) -> rich.repr.Result:
        yield "styles", self.styles

    def __repr__(self) -> str:
        return "StylesBuilder()"

    def error(self, name: str, token: Token, message: str | HelpText) -> NoReturn:
        raise DeclarationError(name, token, message)

    def add_declaration(self, declaration: Declaration) -> None:
        if not declaration.tokens:
            return
        rule_name = declaration.name.replace("-", "_")
        process_method = getattr(self, f"process_{rule_name}", None)

        if process_method is None:
            error_message = f"unknown declaration {declaration.name!r}"
            did_you_mean_rule_name = self._did_you_mean_for_rule_name(declaration.name)
            if did_you_mean_rule_name:
                error_message += f"; did you mean {did_you_mean_rule_name!r}?"
            self.error(
                declaration.name,
                declaration.token,
                error_message,
            )
            return

        tokens = declaration.tokens

        important = tokens[-1].name == "important"
        if important:
            tokens = tokens[:-1]
            self.styles.important.add(rule_name)
        try:
            process_method(declaration.name, tokens)
        except DeclarationError:
            raise
        except Exception as error:
            self.error(declaration.name, declaration.token, str(error))

    @lru_cache(maxsize=None)
    def _processable_rule_names(self) -> frozenset[str]:
        return frozenset(
            [attr[8:] for attr in dir(self) if attr.startswith("process_")]
        )

    def _process_enum_multiple(
        self, name: str, tokens: list[Token], valid_values: set[str], count: int
    ) -> tuple[str, ...]:
        """Generic code to process a declaration with two enumerations, like overflow: auto auto"""
        if len(tokens) > count or not tokens:
            self.error(name, tokens[0], f"expected 1 to {count} tokens here")
        results: list[str] = []
        append = results.append
        for token in tokens:
            token_name, value, _, _, location, _ = token
            if token_name != "token":
                self.error(
                    name,
                    token,
                    f"invalid token {value!r}; expected {friendly_list(valid_values)}",
                )
            append(value)

        short_results = results[:]

        while len(results) < count:
            results.extend(short_results)
        results = results[:count]

        return tuple(results)

    def _process_enum(
        self, name: str, tokens: list[Token], valid_values: set[str]
    ) -> str:
        """Process a declaration that expects an enum.

        Args:
            name (str): Name of declaration.
            tokens (list[Token]): Tokens from parser.
            valid_values (list[str]): A set of valid values.

        Returns:
            bool: True if the value is valid or False if it is invalid (also generates an error)
        """

        if len(tokens) != 1:
            string_enum_help_text(name, valid_values=list(valid_values), context="css"),

        token = tokens[0]
        token_name, value, _, _, location, _ = token
        if token_name != "token":
            self.error(
                name,
                token,
                string_enum_help_text(
                    name, valid_values=list(valid_values), context="css"
                ),
            )
        if value not in valid_values:
            self.error(
                name,
                token,
                string_enum_help_text(
                    name, valid_values=list(valid_values), context="css"
                ),
            )
        return value

    def process_display(self, name: str, tokens: list[Token]) -> None:
        for token in tokens:
            name, value, _, _, location, _ = token

            if name == "token":
                value = value.lower()
                if value in VALID_DISPLAY:
                    self.styles._rules["display"] = cast(Display, value)
                else:
                    self.error(
                        name,
                        token,
                        string_enum_help_text(
                            "display", valid_values=list(VALID_DISPLAY), context="css"
                        ),
                    )
            else:
                self.error(
                    name,
                    token,
                    string_enum_help_text(
                        "display", valid_values=list(VALID_DISPLAY), context="css"
                    ),
                )

    def _process_scalar(self, name: str, tokens: list[Token]) -> None:
        def scalar_error():
            self.error(
                name, tokens[0], scalar_help_text(property_name=name, context="css")
            )

        if not tokens:
            return
        if len(tokens) == 1:
            try:
                self.styles._rules[name.replace("-", "_")] = Scalar.parse(
                    tokens[0].value
                )
            except ScalarParseError:
                scalar_error()
        else:
            scalar_error()

    def process_box_sizing(self, name: str, tokens: list[Token]) -> None:
        for token in tokens:
            name, value, _, _, location, _ = token

            if name == "token":
                value = value.lower()
                if value in VALID_BOX_SIZING:
                    self.styles._rules["box_sizing"] = cast(BoxSizing, value)
                else:
                    self.error(
                        name,
                        token,
                        string_enum_help_text(
                            "box-sizing",
                            valid_values=list(VALID_BOX_SIZING),
                            context="css",
                        ),
                    )
            else:
                self.error(
                    name,
                    token,
                    string_enum_help_text(
                        "box-sizing", valid_values=list(VALID_BOX_SIZING), context="css"
                    ),
                )

    def process_width(self, name: str, tokens: list[Token]) -> None:
        self._process_scalar(name, tokens)

    def process_height(self, name: str, tokens: list[Token]) -> None:
        self._process_scalar(name, tokens)

    def process_min_width(self, name: str, tokens: list[Token]) -> None:
        self._process_scalar(name, tokens)

    def process_min_height(self, name: str, tokens: list[Token]) -> None:
        self._process_scalar(name, tokens)

    def process_max_width(self, name: str, tokens: list[Token]) -> None:
        self._process_scalar(name, tokens)

    def process_max_height(self, name: str, tokens: list[Token]) -> None:
        self._process_scalar(name, tokens)

    def process_overflow(self, name: str, tokens: list[Token]) -> None:
        rules = self.styles._rules
        overflow_x, overflow_y = self._process_enum_multiple(
            name, tokens, VALID_OVERFLOW, 2
        )
        rules["overflow_x"] = cast(Overflow, overflow_x)
        rules["overflow_y"] = cast(Overflow, overflow_y)

    def process_overflow_x(self, name: str, tokens: list[Token]) -> None:
        self.styles._rules["overflow_x"] = cast(
            Overflow, self._process_enum(name, tokens, VALID_OVERFLOW)
        )

    def process_overflow_y(self, name: str, tokens: list[Token]) -> None:
        self.styles._rules["overflow_y"] = cast(
            Overflow, self._process_enum(name, tokens, VALID_OVERFLOW)
        )

    def process_visibility(self, name: str, tokens: list[Token]) -> None:
        for token in tokens:
            name, value, _, _, location, _ = token
            if name == "token":
                value = value.lower()
                if value in VALID_VISIBILITY:
                    self.styles._rules["visibility"] = cast(Visibility, value)
                else:
                    self.error(
                        name,
                        token,
                        string_enum_help_text(
                            "visibility",
                            valid_values=list(VALID_VISIBILITY),
                            context="css",
                        ),
                    )
            else:
                string_enum_help_text(
                    "visibility", valid_values=list(VALID_VISIBILITY), context="css"
                )

    def process_opacity(self, name: str, tokens: list[Token]) -> None:
        if not tokens:
            return
        token = tokens[0]
        error = False
        if len(tokens) != 1:
            error = True
        else:
            token_name = token.name
            value = token.value
            if token_name == "scalar" and value.endswith("%"):
                percentage = value[:-1]
                try:
                    opacity = clamp(float(percentage) / 100, 0, 1)
                    self.styles.set_rule(name, opacity)
                except ValueError:
                    error = True
            elif token_name == "number":
                try:
                    opacity = clamp(float(value), 0, 1)
                    self.styles.set_rule(name, opacity)
                except ValueError:
                    error = True
            else:
                error = True

        if error:
            self.error(name, token, fractional_property_help_text(name, context="css"))

    def _process_space(self, name: str, tokens: list[Token]) -> None:
        space: list[int] = []
        append = space.append
        for token in tokens:
            token_name, value, _, _, _, _ = token
            if token_name == "number":
                try:
                    append(int(value))
                except ValueError:
                    self.error(name, token, spacing_invalid_value(name, context="css"))
            else:
                self.error(name, token, spacing_invalid_value(name, context="css"))
        if len(space) not in (1, 2, 4):
            self.error(
                name,
                tokens[0],
                spacing_wrong_number_of_values(
                    name, num_values_supplied=len(space), context="css"
                ),
            )
        self.styles._rules[name] = Spacing.unpack(cast(SpacingDimensions, tuple(space)))

    def _process_space_partial(self, name: str, tokens: list[Token]) -> None:
        """Process granular margin / padding declarations."""
        if len(tokens) != 1:
            self.error(name, tokens[0], spacing_invalid_value(name, context="css"))

        _EDGE_SPACING_MAP = {"top": 0, "right": 1, "bottom": 2, "left": 3}
        token = tokens[0]
        token_name, value, _, _, _, _ = token
        if token_name == "number":
            space = int(value)
        else:
            self.error(name, token, spacing_invalid_value(name, context="css"))
        style_name, _, edge = name.replace("-", "_").partition("_")

        current_spacing = cast(
            "tuple[int, int, int, int]",
            self.styles._rules.get(style_name, (0, 0, 0, 0)),
        )

        spacing_list = list(current_spacing)
        spacing_list[_EDGE_SPACING_MAP[edge]] = space

        self.styles._rules[style_name] = Spacing(*spacing_list)

    process_padding = _process_space
    process_margin = _process_space

    process_margin_top = _process_space_partial
    process_margin_right = _process_space_partial
    process_margin_bottom = _process_space_partial
    process_margin_left = _process_space_partial

    process_padding_top = _process_space_partial
    process_padding_right = _process_space_partial
    process_padding_bottom = _process_space_partial
    process_padding_left = _process_space_partial

    def _parse_border(self, name: str, tokens: list[Token]) -> tuple[str, Color]:
        border_type = "solid"
        border_color = Color(0, 255, 0)

        def border_value_error():
            self.error(name, token, border_property_help_text(name, context="css"))

        for token in tokens:
            token_name, value, _, _, _, _ = token
            if token_name == "token":
                if value in VALID_BORDER:
                    border_type = value
                else:
                    try:
                        border_color = Color.parse(value)
                    except ColorParseError:
                        border_value_error()

            elif token_name == "color":
                try:
                    border_color = Color.parse(value)
                except ColorParseError:
                    border_value_error()

            else:
                border_value_error()

        return (border_type, border_color)

    def _process_border_edge(self, edge: str, name: str, tokens: list[Token]) -> None:
        border = self._parse_border(name, tokens)
        self.styles._rules[f"border_{edge}"] = border

    def process_border(self, name: str, tokens: list[Token]) -> None:
        border = self._parse_border(name, tokens)
        rules = self.styles._rules
        rules["border_top"] = rules["border_right"] = border
        rules["border_bottom"] = rules["border_left"] = border

    def process_border_top(self, name: str, tokens: list[Token]) -> None:
        self._process_border_edge("top", name, tokens)

    def process_border_right(self, name: str, tokens: list[Token]) -> None:
        self._process_border_edge("right", name, tokens)

    def process_border_bottom(self, name: str, tokens: list[Token]) -> None:
        self._process_border_edge("bottom", name, tokens)

    def process_border_left(self, name: str, tokens: list[Token]) -> None:
        self._process_border_edge("left", name, tokens)

    def _process_outline(self, edge: str, name: str, tokens: list[Token]) -> None:
        border = self._parse_border(name, tokens)
        self.styles._rules[f"outline_{edge}"] = border

    def process_outline(self, name: str, tokens: list[Token]) -> None:
        border = self._parse_border(name, tokens)
        rules = self.styles._rules
        rules["outline_top"] = rules["outline_right"] = border
        rules["outline_bottom"] = rules["outline_left"] = border

    def process_outline_top(self, name: str, tokens: list[Token]) -> None:
        self._process_outline("top", name, tokens)

    def process_parse_border_right(self, name: str, tokens: list[Token]) -> None:
        self._process_outline("right", name, tokens)

    def process_outline_bottom(self, name: str, tokens: list[Token]) -> None:
        self._process_outline("bottom", name, tokens)

    def process_outline_left(self, name: str, tokens: list[Token]) -> None:
        self._process_outline("left", name, tokens)

    def process_offset(self, name: str, tokens: list[Token]) -> None:
        def offset_error(name: str, token: Token) -> None:
            self.error(name, token, offset_property_help_text(context="css"))

        if not tokens:
            return
        if len(tokens) != 2:
            offset_error(name, tokens[0])
        else:
            token1, token2 = tokens

            if token1.name not in ("scalar", "number"):
                offset_error(name, token1)
            if token2.name not in ("scalar", "number"):
                offset_error(name, token2)

            scalar_x = Scalar.parse(token1.value, Unit.WIDTH)
            scalar_y = Scalar.parse(token2.value, Unit.HEIGHT)
            self.styles._rules["offset"] = ScalarOffset(scalar_x, scalar_y)

    def process_offset_x(self, name: str, tokens: list[Token]) -> None:
        if not tokens:
            return
        if len(tokens) != 1:
            self.error(name, tokens[0], offset_single_axis_help_text(name))
        else:
            token = tokens[0]
            if token.name not in ("scalar", "number"):
                self.error(name, token, offset_single_axis_help_text(name))
            x = Scalar.parse(token.value, Unit.WIDTH)
            y = self.styles.offset.y
            self.styles._rules["offset"] = ScalarOffset(x, y)

    def process_offset_y(self, name: str, tokens: list[Token]) -> None:
        if not tokens:
            return
        if len(tokens) != 1:
            self.error(name, tokens[0], offset_single_axis_help_text(name))
        else:
            token = tokens[0]
            if token.name not in ("scalar", "number"):
                self.error(name, token, offset_single_axis_help_text(name))
            y = Scalar.parse(token.value, Unit.HEIGHT)
            x = self.styles.offset.x
            self.styles._rules["offset"] = ScalarOffset(x, y)

    def process_layout(self, name: str, tokens: list[Token]) -> None:
        from ..layouts.factory import get_layout, MissingLayout

        if tokens:
            if len(tokens) != 1:
                self.error(
                    name, tokens[0], layout_property_help_text(name, context="css")
                )
            else:
                value = tokens[0].value
                layout_name = value
                try:
                    self.styles._rules["layout"] = get_layout(layout_name)
                except MissingLayout:
                    self.error(
                        name,
                        tokens[0],
                        layout_property_help_text(name, context="css"),
                    )

    def process_color(self, name: str, tokens: list[Token]) -> None:
        """Processes a simple color declaration."""
        name = name.replace("-", "_")
        for token in tokens:
            if token.name in ("color", "token"):
                try:
                    self.styles._rules[name] = Color.parse(token.value)
                except Exception:
                    self.error(
                        name, token, color_property_help_text(name, context="css")
                    )
            else:
                self.error(name, token, color_property_help_text(name, context="css"))

    process_background = process_color
    process_scrollbar_color = process_color
    process_scrollbar_color_hover = process_color
    process_scrollbar_color_active = process_color
    process_scrollbar_background = process_color
    process_scrollbar_background_hover = process_color
    process_scrollbar_background_active = process_color

    def process_text_style(self, name: str, tokens: list[Token]) -> None:
        for token in tokens:
            value = token.value
            if value not in VALID_STYLE_FLAGS:
                self.error(
                    name,
                    token,
                    style_flags_property_help_text(name, value, context="css"),
                )

        style_definition = " ".join(token.value for token in tokens)
        self.styles.text_style = style_definition

    def process_dock(self, name: str, tokens: list[Token]) -> None:

        if len(tokens) > 1:
            self.error(
                name,
                tokens[1],
                dock_property_help_text(name, context="css"),
            )
        self.styles._rules["dock"] = tokens[0].value if tokens else ""

    def process_docks(self, name: str, tokens: list[Token]) -> None:
        def docks_error(name, token):
            self.error(name, token, docks_property_help_text(name, context="css"))

        docks: list[DockGroup] = []
        for token in tokens:
            if token.name == "key_value":
                key, edge_name = token.value.split("=")
                edge_name = edge_name.strip().lower()
                edge_name, _, number = edge_name.partition("/")
                z = 0
                if number:
                    if not number.isdigit():
                        docks_error(name, token)
                    z = int(number)
                if edge_name not in VALID_EDGE:
                    docks_error(name, token)
                docks.append(DockGroup(key.strip(), cast(Edge, edge_name), z))
            elif token.name == "bar":
                pass
            else:
                docks_error(name, token)
        self.styles._rules["docks"] = tuple(docks + [DockGroup("_default", "top", 0)])

    def process_layer(self, name: str, tokens: list[Token]) -> None:
        if len(tokens) > 1:
            self.error(name, tokens[1], f"unexpected tokens in dock-edge declaration")
        self.styles._rules["layer"] = tokens[0].value

    def process_layers(self, name: str, tokens: list[Token]) -> None:
        layers: list[str] = []
        for token in tokens:
            if token.name != "token":
                self.error(name, token, "{token.name} not expected here")
            layers.append(token.value)
        self.styles._rules["layers"] = tuple(layers)

    def process_transition(self, name: str, tokens: list[Token]) -> None:
        transitions: dict[str, Transition] = {}

        def make_groups() -> Iterable[list[Token]]:
            """Batch tokens into comma-separated groups."""
            group: list[Token] = []
            for token in tokens:
                if token.name == "comma":
                    if group:
                        yield group
                    group = []
                else:
                    group.append(token)
            if group:
                yield group

        valid_duration_token_names = ("duration", "number")
        for tokens in make_groups():
            css_property = ""
            duration = 1.0
            easing = "linear"
            delay = 0.0

            try:
                iter_tokens = iter(tokens)
                token = next(iter_tokens)
                if token.name != "token":
                    self.error(name, token, "expected property")

                css_property = token.value
                token = next(iter_tokens)
                if token.name not in valid_duration_token_names:
                    self.error(name, token, "expected duration or number")
                try:
                    duration = _duration_as_seconds(token.value)
                except ScalarError as error:
                    self.error(name, token, str(error))

                token = next(iter_tokens)
                if token.name != "token":
                    self.error(name, token, "easing function expected")

                if token.value not in EASING:
                    self.error(
                        name,
                        token,
                        f"expected easing function; found {token.value!r}",
                    )
                easing = token.value

                token = next(iter_tokens)
                if token.name not in valid_duration_token_names:
                    self.error(name, token, "expected duration or number")
                try:
                    delay = _duration_as_seconds(token.value)
                except ScalarError as error:
                    self.error(name, token, str(error))
            except StopIteration:
                pass
            transitions[css_property] = Transition(duration, easing, delay)

        self.styles._rules["transitions"] = transitions

    def process_align(self, name: str, tokens: list[Token]) -> None:
        def align_error(name, token):
            self.error(name, token, align_help_text())

        if len(tokens) != 2:
            self.error(name, tokens[0], align_help_text())

        token_horizontal = tokens[0]
        token_vertical = tokens[1]

        if token_horizontal.name != "token":
            align_error(name, token_horizontal)
        elif token_horizontal.value not in VALID_ALIGN_HORIZONTAL:
            align_error(name, token_horizontal)

        if token_vertical.name != "token":
            align_error(name, token_vertical)
        elif token_vertical.value not in VALID_ALIGN_VERTICAL:
            align_error(name, token_horizontal)

        name = name.replace("-", "_")
        self.styles._rules[f"{name}_horizontal"] = token_horizontal.value
        self.styles._rules[f"{name}_vertical"] = token_vertical.value

    def process_align_horizontal(self, name: str, tokens: list[Token]) -> None:
        try:
            value = self._process_enum(name, tokens, VALID_ALIGN_HORIZONTAL)
        except StyleValueError:
            self.error(
                name,
                tokens[0],
                string_enum_help_text(name, VALID_ALIGN_HORIZONTAL, context="css"),
            )
        else:
            self.styles._rules[name.replace("-", "_")] = value

    def process_align_vertical(self, name: str, tokens: list[Token]) -> None:
        try:
            value = self._process_enum(name, tokens, VALID_ALIGN_VERTICAL)
        except StyleValueError:
            self.error(
                name,
                tokens[0],
                string_enum_help_text(name, VALID_ALIGN_VERTICAL, context="css"),
            )
        else:
            self.styles._rules[name.replace("-", "_")] = value

    process_content_align = process_align
    process_content_align_horizontal = process_align_horizontal
    process_content_align_vertical = process_align_vertical

    def _did_you_mean_for_rule_name(self, rule_name: str) -> str | None:
        possible_matches = get_close_matches(
            rule_name, self._processable_rule_names(), n=1
        )
        return None if not possible_matches else possible_matches[0]

import abc, pathlib, typing
import xml.sax
from xml.sax.handler import ContentHandler

import dateutil.parser


T = typing.TypeVar("T")
T_co = typing.TypeVar("T_co", covariant=True)
T_ct = typing.TypeVar("T_ct", contravariant=True)

_TagSequence = typing.Optional[typing.Sequence[str]]


def is_datestring(value: object):
    try:
        return bool(dateutil.parser.parse(value)) #type: ignore[arg-type]
    except (ValueError, TypeError):
        return False


def is_floatstring(value: object):
    return isinstance(value, str) and value.replace(".", "").isnumeric()


def is_numberstring(value: object):
    return isinstance(value, str) and value.isnumeric()


class SupportsAppend(typing.Protocol[T_ct]):

    @abc.abstractmethod
    def append(self, item: T_ct) -> None:
        """Inserts item at top of stack."""


class SupportsPop(typing.Protocol[T_co]):

    @abc.abstractmethod
    def pop(self) -> T_co:
        """
        Removes item from top of stack and
        returns that item.
        """


class SupportsGetItem(typing.Protocol[T_co]):

    @abc.abstractmethod
    def __getitem__(self, index) -> T_co:
        ...


class LIFOStack(SupportsAppend[T], SupportsPop[T], SupportsGetItem[T]):
    ...


class XNATSmartField:
    _public_name: str
    _private_name: str

    def parse(self, value):
        """
        Parse the value from this descriptor.
        """

        if is_datestring(value):
            return dateutil.parser.parse(value)
        if is_floatstring(value):
            return float(value)
        if is_numberstring(value):
            return int(value)

        return value

    def __set_name__(self, owner, name):
        self._public_name = name
        self._private_name = "".join(["__", owner.__name__, "_", name])

    def __get__(self, inst, owner=None):
        if owner is None:
            return self #type: ignore[return-value]

        rt = getattr(inst, self._private_name)
        return rt

    def __set__(self, inst, value) -> None:
        value = self.parse(value)
        setattr(inst, self._private_name, value)

    def __delete__(self, inst) -> None:
        delattr(inst, self._private_name)


class XNATElement:
    """
    Represents a node of some XML tree.
    """

    _parent: typing.Self | None
    _name: str
    _attributes: dict | None
    _children: list[typing.Self] | None
    _value: XNATSmartField = XNATSmartField()

    # Name to index mapping. Holds multiple
    # indexes per name as tags are not unique.
    _child_register: dict[str, set[int]]

    @property
    def name(self) -> str:
        """Name of this element."""

        return self._name

    @property
    def value(self) -> XNATSmartField:
        """Value of this element."""

        return self._value

    @value.setter
    def value(self, value: str):
        self._value = value

    @property
    def attributes(self) -> dict[str, typing.Any]:
        """
        Attributes that belong to this element.
        """

        if self._attributes is None:
            raise AttributeError(f"Instance of node {self} has no attributes")
        return self._attributes

    @property
    def children(self) -> list[typing.Self]:
        """
        Returns the top-level child nodes.
        """

        if self._children is None:
            raise AttributeError(f"Instance of node {self} has no children")
        return self._children

    @property
    def node_count(self) -> int:
        """
        Total count of all nodes from this
        element and below.
        """

        if self._children is None:
            return 1
        return sum([node.node_count for node in self._children])

    @property
    def node_names(self) -> tuple[str, ...]:
        """
        Tag names associated with the top-level
        child nodes.
        """

        return tuple(self._child_register.keys())

    @property
    def parent(self) -> typing.Self:
        """The parent node of this element."""

        if self._parent is None:
            raise AttributeError(f"Instance of node {self} has no parent")
        return self._parent

    @property
    def parents(self) -> typing.Generator[typing.Self, None, None]:
        """
        The path of parent nodes from this
        element to the root.
        """

        node = self._parent
        while node is not None:
            yield node
            node = node._parent

    def __getattribute__(self, name: str):
        try:
            return super().__getattribute__(name)
        except AttributeError:
            # Super getter failed. Do lookup on
            # nodes.
            ...

        if name not in self._child_register:
            raise AttributeError(f"{self} has no {name} child instances.")

        nodes = list[typing.Self]()
        for idx in self._child_register[name]:
            nodes.append(self.children[idx]) #type: ignore[arg-type]
        return nodes

    def __init__(
            self,
            name: str,
            parent: typing.Self | None,
            *,
            attributes: dict | None = None):

        self._parent = parent
        self._name = name
        self._attributes = attributes or {}
        self._children = []
        self._value = ""
        self._child_register = {}

    def __str__(self):
        return self._repr_base(self)

    def __repr__(self):
        metadata = []

        if self._value:
            metadata.append(f"value={self._value!r}")
        if self._attributes:
            metadata.append(f"attributes={self.attributes!r}")

        if self._children:
            children = ", ".join([self._repr_base(c) for c in self._children])
            metadata.append(f"children={{{children}}}")

        metadata = ", ".join(metadata)
        return f"{self._repr_base(self)}({metadata})"

    def _clean(self):
        if isinstance(self._value, str):
            self._value = self._value.strip() #type: ignore
        elif not self._value:
            self._value = None

        for attr in ("_attributes", "_children", "_value", "_child_register"):
            if not getattr(self, attr):
                setattr(self, attr, None)

    def _put_child(self, item: typing.Self):
        self.children.append(item)

        name, index = item.name.replace(":", "_"), (len(self.children) - 1)
        if not name in self._child_register:
            self._child_register[name] = set([index])
        else:
            self._child_register[name].add(index)

    @classmethod
    def _repr_base(cls, element: typing.Self):
        return f"{element.__class__.__name__}[{element.name}]"


class XNATContentHandler(ContentHandler):
    _element_stack: LIFOStack[XNATElement]
    _element_include_tags: typing.Sequence[str]
    _element_exclude_tags: typing.Sequence[str]

    @property
    def root(self):
        """The first element in the tree."""

        return self._element_stack[0]

    @property
    def current_element(self):
        """
        The node at the end of the element stack.
        """

        try:
            return self._element_stack[-1]
        except IndexError:
            return None

    @property
    def stack_size(self):
        """Current size of the element stack."""

        return len(self._element_stack)

    def __init__(
            self,
            *,
            include_tags: typing.Optional[_TagSequence] = None,
            exclude_tags: typing.Optional[_TagSequence] = None):

        super().__init__()
        self._element_stack = list() #type: ignore[assignment]
        self._element_include_tags = include_tags or []
        self._element_exclude_tags = exclude_tags or []

    def startElement(self, name, attrs):
        self._put_element(XNATElement(
            name,
            self.current_element,
            attributes=dict(attrs)))

    def endElement(self, name):
        self.current_element._clean()
        if self.stack_size < 2:
            return

        child = self._pop_element()

        # Only include child node if child's name
        # is not in the exclusion list.
        if child.name in self._element_exclude_tags:
            return

        # If there is no whitelist add child
        # nodes indiscrimintely.
        if not self._element_include_tags:
            self.current_element._put_child(child)
            return

        # If the current child node is in the
        # whitelist, add it directly and move on.
        if child.name in self._element_include_tags:
            self.current_element._put_child(child)
            return

        # Look for proof that this node is a
        # child of some node that is allowed in
        # the whitelist.
        for node in child.parents:
            if node.name in self._element_include_tags:
                self.current_element._put_child(child)
                return

        # Last ditch effort to ensure child node
        # is not parent to whitelisted tags.
        if not child.node_count - 1:
            return

        for node in child.children:
            if node.name in self._element_include_tags:
                self.current_element._put_child(child)
                return

    def characters(self, content):
        self.current_element.value += content

    def _pop_element(self):
        return self._element_stack.pop()

    def _put_element(self, item: XNATElement):
        self._element_stack.append(item)


def build_handler(
    include_tags: typing.Optional[_TagSequence] = None,
    exclude_tags: typing.Optional[_TagSequence] = None):

    return XNATContentHandler\
    (
        include_tags=include_tags,
        exclude_tags=exclude_tags
    )

def parse_file(path: pathlib.Path | str, **kwds):
    if isinstance(path, str):
        path = pathlib.Path(path)

    handler = build_handler(**kwds)
    xml.sax.parse(path.absolute().as_posix(), handler)
    return handler.root


def parse_buffer(buffer: str, **kwds):
    handler = build_handler(**kwds)
    xml.sax.parseString(buffer, handler)
    return handler.root


if __name__ == "__main__":
    import pathlib

    tree = parse_file("path/to/file.xml", include_tags=["xnat:scan"])

    print("node_count:", tree.node_count)
    print("node_names:", tree.node_names)

    # This attribute should exist @ runtime.
    # dynamic attrs will be added as tags are
    # added to the root element.
    print(tree.xnat_scans[0].xnat_scan[0])

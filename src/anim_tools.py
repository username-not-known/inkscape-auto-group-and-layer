#!/usr/bin/env python3
"""
BSD-3

Originally by suv-sf@users.sf.net

"""

from copy import deepcopy
import inkex
from inkex import Group, Layer, Use, PathElement, Transform, Path

# globals
ZFILL = 5


def is_group(node):
    """Check whether node is SVG group element."""
    return isinstance(node, Group) or node.tag == inkex.addNS('g', 'svg')


def is_layer(node):
    """Check whether node is Inkscape layer."""
    return isinstance(node, Layer) or (
        node.tag == inkex.addNS('g', 'svg') and
        node.get(inkex.addNS('groupmode', 'inkscape')) == 'layer'
    )


def sublayer_objs(layer, rev=False):
    """Iterate through sublayers of layer, return sub-layer node."""
    children = list(layer)
    if rev:
        children.reverse()
    for node in children:
        if is_layer(node):
            yield node


def wrap_in_group(node):
    """Wrap node in group, return group."""
    group = Group()
    parent = node.getparent()
    index = parent.index(node)
    parent.insert(index, group)
    group.append(node)
    return group


def group_to_layer(node):
    """Add inkscape groupmode attribute and set it to 'layer'."""
    if is_group(node):
        node.set(inkex.addNS('groupmode', 'inkscape'), 'layer')


def layer_to_group(node):
    """Remove inkscape groupmode attribute if present."""
    if is_layer(node):
        key = inkex.addNS('groupmode', 'inkscape')
        if key in node.attrib:
            del node.attrib[key]


# Transformation matrix utilities

def mat_copy_from(node):
    """Return transformation matrix for node's preserved transform."""
    return Transform(node.get('transform'))


def mat_apply_to(mat, obj):
    """Apply transform matrix to element or path."""
    if isinstance(obj, Path):
        obj.transform(mat)
    elif isinstance(obj, inkex.BaseElement):
        obj.transform = mat @ obj.transform


def mat_absolute(node):
    """Return transformation matrix transforming node to SVGRoot."""
    return node.composed_transform()


def mat_apply_copy_from(source, target):
    """Apply preserved transform from source to target."""
    mat = mat_copy_from(source)
    mat_apply_to(mat, target)


def mat_absolute_diff(node1, node2):
    """Return transformation matrix to transform node2 to node1 coords."""
    mat1 = mat_absolute(node1.getparent())
    mat2 = mat_absolute(node2.getparent())
    return (-mat1) @ mat2


def mat_apply_absolute_diff(node1, node2):
    """Transform node2 to node1 coords."""
    mat = mat_absolute_diff(node1, node2)
    mat_apply_to(mat, node2)


def ref_node(doc, node):
    """Return element linked to via href (e.g. by <use> elements)."""
    href = node.get(inkex.addNS('href', 'xlink')) or node.get('href')
    if href and href.startswith('#'):
        return doc.getElementById(href[1:])
    return None


def resolve_use(doc, node):
    """Recursively process <use> elements and convert into groups."""
    group = Group()
    if node.get('transform'):
        group.transform = Transform(node.get('transform'))
    mat = Transform(f"translate({node.get('x', 0)},{node.get('y', 0)})")
    group.transform = mat @ group.transform

    node_orig = ref_node(doc, node)
    if node_orig is not None:
        if isinstance(node_orig, Use):
            use_group = resolve_use(doc, node_orig)
            group.append(use_group)
        elif is_group(node_orig):
            sub_group = resolve_group(doc, node_orig)
            group.append(sub_group)
        else:
            group.append(deepcopy(node_orig))
    else:
        inkex.errormsg(f'Orphaned clone ({node.get("id")}) ignored.')
    return group


def resolve_group(doc, node):
    """Recursively process groups, follow links of <use> childs."""
    group = Group()
    if node.get('transform'):
        group.set('transform', node.get('transform'))
    for child in node:
        if isinstance(child, Use):
            use_group = resolve_use(doc, child)
            group.append(use_group)
        elif is_group(child):
            sub_group = resolve_group(doc, child)
            group.append(sub_group)
        else:
            group.append(deepcopy(child))
    return group


def copy_group_unlink_recursively(group):
    """Return new group with copy of the <g>'s content."""
    doc = group.root
    new_group = Group()
    if group.get('transform'):
        new_group.transform = Transform(group.get('transform'))
    if len(group) > 0:
        for child in group:
            if isinstance(child, Use):
                use_group = resolve_use(doc, child)
                new_group.append(use_group)
            elif is_group(child):
                sub_group = resolve_group(doc, child)
                new_group.append(sub_group)
            else:
                new_group.append(deepcopy(child))
    index = group.getparent().index(group)
    group.getparent().insert(index + 1, new_group)
    return new_group


def ungroup_path(group):
    """Recursively extract cubic paths from group."""
    mat = Transform(group.get('transform'))
    group_csp = Path()
    for child in group:
        if child.tag == inkex.addNS('desc', 'svg'):
            pass
        elif is_group(child):
            cspp = ungroup_path(child)
            cspp.transform(mat)
            group_csp.extend(cspp)
        elif isinstance(child, PathElement) or child.tag == inkex.addNS('path', 'svg'):
            if child.get('d'):
                cspp = Path(child.get('d'))
                cspp.transform(mat)
                group_csp.extend(cspp)
    return group_csp


def ungroup_combine(group):
    """Ungroup group content and combine into single path."""
    group_csp = ungroup_path(group)
    group_path = PathElement()
    group_path.set('d', str(group_csp))
    index = group.getparent().index(group)
    group.getparent().insert(index + 1, group_path)
    return group_path


def zip_two_groups(group1, group2, offset=0):
    """Insert (zip) children of group2 into group1."""
    if is_group(group1) and is_group(group2):
        len_group1 = len(group1)
        if offset > 0:
            offset = min(offset, len_group1)
        elif offset < 0:
            offset = max(offset, -1 * len(group2))
        for i, node in enumerate(list(group2)):
            mat_apply_absolute_diff(group1[0], node)
            if offset + i < 0:
                group1.insert(i, node)
            elif offset + i <= len_group1:
                group1.insert(offset + 2 * i + 1, node)
            else:
                group1.append(node)
        group2.getparent().remove(group2)


def copy_node_into_group(source, target, merge=False):
    """Helper function for zipping/merging into subgroups."""
    new_node = deepcopy(source)
    mat_apply_to(mat_absolute_diff(target, source), new_node)
    if merge:
        mat_apply_to(-mat_copy_from(target), new_node)
    target.append(new_node)


def copy_node_or_group(source, target, merge=False):
    """Check type and recursively copy content if source is container."""
    if not is_group(source):
        copy_node_into_group(source, target, merge)
    else:
        for child in source:
            copy_node_into_group(child, target, merge)


def zip_into_subgroups(group1, group2, offset=0):
    """Merge children of group1 and group2 into subgroup in new group."""
    if is_group(group1) and is_group(group2):
        parent_group = Group()
        group2.getparent().append(parent_group)
        if offset >= 0:
            offset = min(offset, len(group1))
            max_count = max(len(group1), offset + len(group2))
        else:
            offset = max(offset, -len(group2))
            max_count = -offset + max(len(group1), offset + len(group2))
        for i in range(max_count):
            zip_group = Group()
            parent_group.append(zip_group)
            j = offset + i if offset < 0 else i
            if j < 0:  # prepend from group2
                copy_node_or_group(group2[i], zip_group)
            else:
                if j + 1 <= len(group1):  # copy from group1
                    copy_node_or_group(group1[j], zip_group)
                if i >= offset and j - offset < len(group2):  # merge group2
                    copy_node_or_group(group2[j - offset], zip_group)
            zip_group.set(
                inkex.addNS('label', 'inkscape'), str(i).zfill(ZFILL))
        return parent_group


def merge_into_subgroups(group1, group2, offset=0, keep=False):
    """Merge children of group2 into subgroups of group1."""
    merge = True
    if is_group(group1) and is_group(group2):
        if offset >= 0:
            offset = min(offset, len(group1))
            max_count = max(len(group1), offset + len(group2))
        else:
            offset = max(offset, -len(group2))
            max_count = -offset + max(len(group1), offset + len(group2))
        for i in range(max_count):
            j = offset + i if offset < 0 else i
            if j < 0:  # prepend from group2
                merge_group = Group()
                group1.insert(i, merge_group)
                copy_node_or_group(group2[i], merge_group, merge)
            else:
                if j + 1 <= len(group1):  # wrap from group1
                    if not is_group(group1[i]):
                        merge_group = wrap_in_group(group1[i])
                    else:
                        merge_group = group1[i]
                else:  # append empty merge group
                    merge_group = Group()
                    group1.append(merge_group)
                if i >= offset and j - offset < len(group2):  # merge group2
                    copy_node_or_group(group2[j - offset], merge_group, merge)
            merge_group.set(
                inkex.addNS('label', 'inkscape'), str(i).zfill(ZFILL))
        if not keep:
            group2.getparent().remove(group2)


class AnimTools(inkex.EffectExtension):
    """Tools to manipulate symbol and icon sets."""

    def __init__(self):
        super().__init__()
        self.objects = []
        self.commonlayers = []

    def add_arguments(self, pars):
        # groups
        pars.add_argument("--action_groups",
                          type=str,
                          dest="action_groups",
                          default="object_to_layer",
                          help="Action for groups tab")
        pars.add_argument("--use_offset",
                          type=inkex.Boolean,
                          dest="use_offset",
                          default=False,
                          help="Apply offset when zipping/merging")
        pars.add_argument("--offset_groups",
                          type=int,
                          dest="offset_groups",
                          default=0,
                          help="Offset value for subgroup zip/merge")
        # layers
        pars.add_argument("--action_layers",
                          type=str,
                          dest="action_layers",
                          default="layer_to_group",
                          help="Action for layers tab")
        # misc
        pars.add_argument("--action_misc",
                          type=str,
                          dest="action_misc",
                          default="ungroup_keep_id",
                          help="Action for misc tab")
        # notebook tab selector
        pars.add_argument("--nb_main",
                          type=str,
                          dest="nb_main",
                          default="page_groups",
                          help="Active notebook tab")

    def convert_layers_to_groups(self):
        """Convert selected layers to groups."""
        for node in self.objects:
            layer_to_group(node)

    def convert_groups_to_layers(self):
        """Convert selected groups to layers."""
        for node in reversed(self.objects):
            parent_layer = node.getparent()
            if parent_layer.getparent() is not None:
                index = parent_layer.getparent().index(parent_layer)
                parent_layer.getparent().insert(index + 1, node)
                mat_apply_copy_from(parent_layer, node)
            group_to_layer(node)

    def convert_groups_to_sublayers(self):
        """Convert selected groups to layers."""
        for node in self.objects:
            group_to_layer(node)

    def unwrap_sublayers_in_layer(self):
        """Move objects from sub-layer to parent, delete sub-layer."""
        for node in self.objects:
            if is_layer(node):
                parent = node.getparent()
                index = parent.index(node)
                for child in list(node):
                    mat_apply_copy_from(node, child)
                    parent.insert(index, child)
                    index += 1
                parent.remove(node)

    def wrap_objects_in_sublayers(self):
        """Wrap each selected object into new sub-layer of parent."""
        for i, node in enumerate(self.objects):
            node_parent = node.getparent()
            if not is_layer(node_parent):
                group_to_layer(node_parent)
                node_parent.set(
                    inkex.addNS('label', 'inkscape'), "anim")
            new_group = wrap_in_group(node)
            new_group.set(
                inkex.addNS('label', 'inkscape'), str(i).zfill(ZFILL))
            group_to_layer(new_group)

    def wrap_objects_in_groups(self):
        """Wrap each selected object in a group."""
        for i, node in enumerate(self.objects):
            new_group = wrap_in_group(node)
            new_group.set(
                inkex.addNS('label', 'inkscape'), str(i).zfill(ZFILL))

    def zip_objects_into_subgroups(self):
        """Wrapper to process more than 2 selected groups for zipping."""
        offset = self.options.offset_groups
        zgroup = zip_into_subgroups(self.objects[0], self.objects[1], offset)
        if len(self.objects) > 2:
            for node in self.objects[2:]:
                if offset >= 0:
                    offset += self.options.offset_groups
                merge_into_subgroups(zgroup, node, offset, keep=True)

    def merge_objects_into_subgroups(self):
        """Wrapper to process more than 2 selected groups for merging."""
        offset = self.options.offset_groups
        for node in self.objects[1:]:
            merge_into_subgroups(self.objects[0], node, offset)
            if offset >= 0:
                offset += self.options.offset_groups

    def ungroup_selection(self, mode="keep_id"):
        """Ungroup single child items preserving transformation and ID."""
        for node in self.objects:
            if len(node) == 1:
                index = node.getparent().index(node)
                child = node[0]
                node.getparent().insert(index, child)
                if mode == 'keep_id':
                    child.set('id', node.get('id'))
                if 'transform' in node.attrib:
                    child.attrib['transform'] = node.attrib['transform']
                node.getparent().remove(node)

    def get_selection(self, mode="object"):
        """Fill instance attribute (list) with refs to target objects."""
        selected_nodes = list(self.svg.selection.values())
        if mode == "object":
            self.objects.extend(selected_nodes)
        elif mode == "group":
            self.objects.extend([n for n in selected_nodes if is_group(n)])
        elif mode == "groupcontent":
            for n in selected_nodes:
                if is_group(n):
                    self.objects.extend(list(n))
        elif mode == "rootlayers":
            self.objects.extend(list(sublayer_objs(self.document.getroot())))
        elif mode == "current_layer":
            self.objects.append(self.svg.get_current_layer())
        elif mode == "sublayers":
            self.objects.extend(list(sublayer_objs(self.svg.get_current_layer())))

    def page_misc(self):
        """Process actions from the Misc tab."""
        if self.options.action_misc == "ungroup_keep_id":
            self.get_selection(mode="group")
            self.ungroup_selection(mode="keep_id")
        elif self.options.action_misc == "ungroup_combine":
            self.get_selection(mode="group")
            for group in self.objects:
                ungroup_combine(group)
        elif self.options.action_misc == "unlink_recursively":
            self.get_selection(mode="group")
            for group in self.objects:
                copy_group_unlink_recursively(group)

    def page_layers(self):
        """Dispatch command for chosen action in layers tab."""
        if self.options.action_layers == "object_to_layer":
            self.get_selection(mode="object")
            self.wrap_objects_in_sublayers()
        elif self.options.action_layers == "group_to_sublayer":
            self.get_selection(mode="group")
            self.convert_groups_to_sublayers()
        elif self.options.action_layers == "groupcontent_to_layer":
            self.get_selection(mode="groupcontent")
            self.wrap_objects_in_sublayers()
        elif self.options.action_layers == "layer_to_group":
            self.get_selection(mode="current_layer")
            self.convert_layers_to_groups()
        elif self.options.action_layers == "layers_to_group":
            self.get_selection(mode="rootlayers")
            self.convert_layers_to_groups()
        elif self.options.action_layers == "group_to_layer":
            self.get_selection(mode="group")
            self.convert_groups_to_layers()
        elif self.options.action_layers == "sublayer_to_group":
            self.get_selection(mode="sublayers")
            self.convert_layers_to_groups()
        elif self.options.action_layers == "unwrap_sublayer":
            self.get_selection(mode="sublayers")
            self.unwrap_sublayers_in_layer()

    def page_groups(self):
        """Dispatch command for chosen action in groups tab."""
        if not self.options.use_offset:
            self.options.offset_groups = 0
        if self.options.action_groups == "object_to_group":
            self.get_selection(mode="object")
            self.wrap_objects_in_groups()
        elif self.options.action_groups == "zip_groups":
            self.get_selection(mode="group")
            if len(self.objects) == 2:
                offset = self.options.offset_groups
                zip_two_groups(self.objects[0], self.objects[1], offset)
        elif self.options.action_groups == "zip_into_subgroups":
            self.get_selection(mode="group")
            if len(self.objects) >= 2:
                self.zip_objects_into_subgroups()
        elif self.options.action_groups == "merge_into_subgroups":
            self.get_selection(mode="group")
            if len(self.objects) >= 2:
                self.merge_objects_into_subgroups()

    def effect(self):
        """Run action dispatcher based on current tab in GUI."""
        active_tab = self.options.nb_main.strip("\"")
        try:
            page_cmd = getattr(self, active_tab)
            page_cmd()
        except AttributeError:
            inkex.errormsg(f'Unknown tab {active_tab}')


if __name__ == '__main__':
    AnimTools().run()

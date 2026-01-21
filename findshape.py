#!/usr/bin/env python
# coding=utf-8

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor,
# Boston, MA  02110-1301, USA.

"""
Finds paths that are the same shape as the selected path, and replaces each with a clone of the selected path.
Finds duplicates with different rotations or flips, as long as they have the same or nearly the same vertices.
"""
import sys
import os
import logging
import numpy as np

import inkex
from inkex import Use, ShapeElement, Transform
from lxml import etree


def str2bool(arg):
    str_arg = str(arg).lower()
    logging.debug(str_arg)
    return str_arg != "false" and str_arg != "0"


class FindShape(inkex.EffectExtension):
    def add_arguments(self, parser):
        parser.add_argument("--findrotate", type=str2bool, default=True)
        parser.add_argument("--findflip", type=str2bool, default=True)
        parser.add_argument("--findresize", type=str2bool, default=True)
        parser.add_argument("--findrescale", type=str2bool, default=True)
        parser.add_argument("--findtype", type=str, default="nodes only")
        parser.add_argument("--maxerr", type=float, default=0)
        parser.add_argument("--avgerr", type=float, default=0)
        parser.add_argument("--replace", type=str2bool, default=False)
        parser.add_argument("--delete", type=str2bool, default=False)
        parser.add_argument("--replacetype", type=str, default="clone")
        parser.add_argument("--replacewhere", type=str, default="same parent as match")

    def effect(self):
        logging.debug(f'{self.svg.selection}')
        logging.debug(f'args: {self.options}')

        # get template
        elements = self.svg.selection.filter_nonzero(ShapeElement)
        if len(elements) != 1:
            logging.error(f'selection contains more than one valid object: {elements}')
            raise ValueError("Must select one object as template.")

        self.template = elements[0]
        logging.debug(f'template {self.template.tostring()}')
        try:
            self.template_nodes, template_translate, template_transform = self.center_path(self.template)
        except Exception as e:
            logging.error(f'could not get path from selection: {e}\n{self.template}')
            raise ValueError("Selected object must be a path.")
        # cache this transform: move template to visible locations, then subtract mean to center around origin
        # note: transforms are applied right to left
        self.template_transform =  (-template_translate) @ template_transform

        # look for other objects in file that match template
        matches = []
        for child in self.svg.descendants():
            if child != self.template:
                logging.debug(f'comparing... {child.get_id()} {type(child)}')
                transform = self.match_object(child)
                if transform is not None:
                    matches.append((child, transform))

        if len(matches) == 0:
            raise ValueError("No matches found")

        # add container for copies if needed
        if self.options.replace:
            container_id = self.svg.get_unique_id(f'{self.template.get_id()}-duplicates')
            if self.options.replacewhere == "same parent as match":
                copy_container = None
            elif self.options.replacewhere == "new group (current layer)":
                copy_container = etree.SubElement(self.svg.get_current_layer(), 'g', {'id': container_id})
                self.svg.selection.add(copy_container.get_id())
            elif self.options.replacewhere == "new layer":
                copy_container = inkex.Layer(id=container_id)
                self.svg.append(copy_container)

        # create copies and/or delete matches
        for child, transform in matches:
            if self.options.replace:
                container = child.getparent() if copy_container is None else copy_container
                logging.debug(f'copy {child.get_id()} to {container.get_id()}')

                if self.options.replacetype == "clone":
                    copy = self.make_clone(container, transform)
                elif self.options.replacetype == "duplicate":
                    raise NotImplementedError()

                if copy_container is not None:
                    self.svg.selection.add(copy.get_id())

            if self.options.delete:
                child.getparent().remove(child)
            else:
                self.svg.selection.add(child.get_id())

    @staticmethod
    def center_path(object):
        """Returns standardized representation of an object as a path centered about the origin,
        and the transformations needed to get there.

        Args:
            object: any element that implements `get_path` (rectangle, circle, etc.)

        Returns:
            Tuple[np.ndarray, np.ndarray, Transform]: the points of the path representation,
                with the object's `composed_transform` applied, and then translated to the origin.
                Also returns the translation vector and the object's `composed_transform`.
        """
        transform = object.composed_transform()
        logging.debug(f'{transform}')
        path = object.get_path()
        nodes = [transform.apply_to_point(vec2d) for vec2d in path.end_points]
        # form matrix of point vectors, each vector has global xy coordinates of node
        nodes = np.array([[vec2d.x, vec2d.y] for vec2d in nodes]).T
        center = np.mean(nodes, axis=1, keepdims=True)
        points = nodes - center
        translate = Transform(((1, 0, 0, 1, center[0, 0], center[1, 0])))
        return points, translate, transform

    @staticmethod
    def orthogonal_procrustes(A, B) -> np.ndarray:
        # find R that minimizes || R A - B ||
        # where A and B are 2xn matrices and R is 2x2
        u, _, vT = np.linalg.svd(B @ A.T)
        return u @ vT

    def match_object(self, object) -> np.ndarray:
        try:
            # don't need the target transform as it's already applied to the nodes, which is what we will try to match
            nodes, translate, _ = self.center_path(object)
        except Exception as e:
            logging.debug(f'could not get path of object: {e}')
            return None

        # check if path has same number of points
        if nodes.shape != self.template_nodes.shape:
            logging.debug(f'number of points differs: {nodes.shape}, target is {self.template_nodes.shape}')
            return None

        # align template to locations of target nodes
        R = self.orthogonal_procrustes(self.template_nodes, nodes)
        if not np.all(np.isfinite(R)):
            logging.debug(f'NaN or infinity in transformation: {R}')
            return None

        # check error (distance between path points)
        transformed_template = R @ self.template_nodes
        mean_error = np.mean((transformed_template - nodes)**2)**0.5
        if mean_error > self.options.avgerr:
            logging.debug(f'average error exceeds {self.options.avgerr}: {mean_error}')
            return None
        max_error = np.max(np.abs(transformed_template - nodes))
        if max_error > self.options.maxerr:
            logging.debug(f'average error exceeds {self.options.maxerr}: {max_error}' )
            return None

        # compose final transform: transform template to origin, match via procrustes, then undo centering
        transform = Transform((R[0, 0], R[1, 0], R[0, 1], R[1, 1], 0, 0))
        logging.info(f'found match: {transform}')
        # note: transforms are applied right to left
        return translate @ transform @ self.template_transform

    def make_clone(self, clone_group, transform: Transform):
        id = self.svg.get_unique_id(f'{self.template.get_id()}-clone')
        # use the Use class from inkex as it nicely formats the transform matrix into a rotation command
        clone = Use.new(self.template, 0, 0, id=id, transform=transform)
        logging.debug(f'cloning as... {clone.tostring()}')
        clone_element = etree.SubElement(clone_group, inkex.addNS('use','svg'), clone.attrib)
        logging.debug(f'{clone_element.tostring()}')
        return clone_element


if __name__ == "__main__":
    logging.basicConfig(filename='debug-log-findshape.txt', filemode='w', format='%(levelname)s: %(message)s', level=logging.DEBUG)
    logging.debug(f'python exec: {sys.executable}')
    logging.debug(f'cwd: {os.getcwd()}')
    logging.debug(f'cmd args: {sys.argv}')
    FindShape().run()

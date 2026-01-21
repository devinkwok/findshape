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


class Shape:
    def __init__(self, object):
        self.object = object
        self.path = object.get_path()
        self.render_transform = object.composed_transform()

        points = [self.render_transform.apply_to_point(vec2d) for vec2d in self.path.end_points]
        self.points = np.array([[vec2d.x, vec2d.y] for vec2d in points]).T
        self.centroid = np.mean(self.points, axis=1, keepdims=True)

    @staticmethod
    def make_transform(size=1.0, matrix=None, translate=None):
        if matrix is not None:
            a, b, c, d = matrix[0, 0], matrix[1, 0], matrix[0, 1], matrix[1, 1]
        else:
            a, b, c, d = 1, 0, 0, 1
        t_x = translate[0, 0] if translate is not None else 0
        t_y = translate[1, 0] if translate is not None else 0
        transform = Transform((a * size, b * size, c * size, d * size, t_x * size, t_y * size))
        logging.debug(f'transform {size} {matrix} {translate}, {transform}')
        return transform

    def get_id(self):
        return self.object.get_id()

    def center(self, return_inverse=False):
        self.points -= self.centroid
        if return_inverse:
            return self.make_transform(translate=self.centroid)
        return self.make_transform(translate=-self.centroid)

    def flip_and_rotate_to(self, shape, return_inverse=False):
        # orthogonal_procrustes finds R that minimizes || R A - B ||
        # where A and B are 2xn matrices and R is 2x2
        u, _, vT = np.linalg.svd(shape.points @ self.points.T)
        R = u @ vT
        if not np.all(np.isfinite(R)):
            logging.info(f'NaN or infinity in transformation: {R}')
            return self.make_transform()
        self.points = R @ self.points
        if return_inverse:
            return self.make_transform(matrix=R.T)
        return self.make_transform(matrix=R)

    def is_similar(self, shape, mean_tolerance, max_tolerance):
        diff = self.points - shape.points
        mean_err = np.mean(diff**2)**0.5
        max_err = np.max(np.abs(diff))
        logging.debug(f'mean_err {mean_err}, max_err {max_err}' )
        return mean_err <= mean_tolerance and max_err <= max_tolerance


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
        try:
            logging.debug(f'template {elements[0].tostring()}')
            self.shape = Shape(self.template)
        except Exception as e:
            logging.error(f'could not get path from selection: {e}\n{self.shape}')
            raise ValueError("Selected object must be a path.")
        # cache this transform: move template to rendered location, then center it
        # note: transforms are applied right to left
        translate_to_center = self.shape.center()
        self.template_transform = translate_to_center @ self.shape.render_transform

        # look for other objects in file that match template
        matches = []
        for child in self.svg.descendants():
            if child == self.template:
                continue  # don't match template to itself
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
                    copy = self.copy(container, transform)
                elif self.options.replacetype == "duplicate":
                    raise NotImplementedError()

                if copy_container is not None:
                    self.svg.selection.add(copy.get_id())

            if self.options.delete:
                child.getparent().remove(child)
            else:
                self.svg.selection.add(child.get_id())

    def match_object(self, object) -> np.ndarray:
        try:
            target = Shape(object)
        except Exception as e:
            logging.debug(f'could not get path of object: {e}')
            return None

        # check if path has same number of points
        if target.points.shape != self.shape.points.shape:
            logging.debug(f'number of points differs: {target.points.shape} and {self.shape.points.shape}')
            return None

        # we want the template -> target transform, so undo centering
        # note: transforms are applied right to left
        transform = target.center(return_inverse=True)

        # align template to locations of target nodes
        if self.options.findrescale:
            raise NotImplementedError  #TODO
        elif self.options.findresize:
            raise NotImplementedError  #TODO

        if self.options.findflip and self.options.findrotate:
            flip_rotate = target.flip_and_rotate_to(self.shape, return_inverse=True)
            transform = transform @ flip_rotate
        elif self.options.findflip:
            raise NotImplementedError  #TODO
        elif self.options.findrotate:
            raise NotImplementedError  #TODO

        # check error (distance between path points)
        if not target.is_similar(self.shape, self.options.avgerr, self.options.maxerr):
            logging.debug(f'error exceeds avg {self.options.avgerr} or max {self.options.maxerr}')
            return None

        # final transform is template -> rendered template -> centered template -> align template to target (flip, rotate, scale, etc.) -> undo centering of target
        transform = transform @ self.template_transform
        logging.info(f'found match: {transform}')
        return transform

    def copy(self, clone_group, transform: Transform):
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

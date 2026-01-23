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


def str2bool(arg):
    str_arg = str(arg).lower()
    return str_arg != "false" and str_arg != "0"


class Shape:
    def __init__(self, object, reverse_path=False, include_handles=True):
        self.object = object
        self.path = object.get_path().to_superpath()
        self.render_transform = object.composed_transform()
        # only allow shapes with single subpath
        if len(self.path) > 1:
            raise ValueError(f'Can only compare connected shapes (those with a single subpath): {self.path}')
        self.path = self.path[0]

        # superpath is 4 nested lists: subpaths, segments, [handle point handle], [x y]
        # note: closed curves have the same first and last points, this will cause problems if cycling the points
        if include_handles:  # include all 3 points per segment
            points = [p for segment in self.path for p in segment]
        else:  # only include the node point
            points = [p for _, p, _ in self.path]
        points = [self.render_transform.apply_to_point(p) for p in points]

        # 2xn, dim 0 is x, y, dim 1 is nodes
        self.points = np.array([[vec2d.x, vec2d.y] for vec2d in points]).T
        if reverse_path:
            self.points = np.flip(self.points, axis=1)
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

    def resize_to(self, shape, return_inverse=False):
        source_size = np.linalg.norm(self.points)
        target_size = np.linalg.norm(shape.points)
        if source_size <= 0 or target_size <= 0:
            return self.make_transform()
        scale_factor = target_size / source_size
        self.points *= scale_factor
        if return_inverse:
            return self.make_transform(size=1 / scale_factor)
        return self.make_transform(size=scale_factor)
    
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
    FINDABLE_OBJECTS = [inkex.PathElement, inkex.Rectangle, inkex.Use, inkex.Ellipse, inkex.Circle]

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

    def is_findable_object(self, object) -> bool:
        return any(isinstance(object, obj_type) for obj_type in self.FINDABLE_OBJECTS)

    def new_id(self, suffix):
        return self.svg.get_unique_id(f'{self.template.get_id()}-{suffix}')

    def get_container(self):
        # add container for copies if missing
        if self.container is None:
            container_id = self.new_id('copies')

            if self.options.replacewhere == "new group (current layer)":
                self.container = inkex.Group(id=container_id)
                self.svg.get_current_layer().append(self.container)
            elif self.options.replacewhere == "new layer":
                self.container = inkex.Layer(id=container_id)
                self.svg.append(self.container)
            else:
                raise RuntimeError(f"Invalid option for copy container: {self.options.replacewhere}")

            self.svg.selection.add(container_id)

        return self.container

    def match_object(self, object, reverse_path=False) -> np.ndarray:
        try:
            target = Shape(object, reverse_path=reverse_path, include_handles=self.include_handles)
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
            # for the points, scale target to match template
            scale = target.resize_to(self.shape, return_inverse=True)
            # for the transform, scale template to match target before undoing centering
            transform = transform @ scale

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

    def copy(self, parent, transform: Transform, clone=False):
        id = self.new_id('clone' if clone else 'duplicate')
        if clone:
            # use the Use class from inkex as it nicely formats the transform matrix into a rotation command
            copy_element = Use.new(self.template, 0, 0, id=id, transform=transform)
        else:
            copy_element = self.template.duplicate()
            copy_element.transform = transform
        parent.append(copy_element)
        logging.debug(f'copied {copy_element.tostring()}')
        return copy_element

    def effect(self):
        logging.debug(f'{self.svg.selection}')
        logging.debug(f'args: {self.options}')
        self.container = None
        self.template = None
        self.copy_to_parent = self.options.replacewhere == "same parent as match"
        self.do_clone = self.options.replacetype == "clone"
        self.include_handles = self.options.findtype == "nodes and handles"

        # get template
        elements = self.svg.selection.filter_nonzero(ShapeElement)
        if len(elements) != 1:
            logging.error(f'selection contains more than one valid object: {elements}')
            raise ValueError("Must select one object as template.")

        self.template = elements[0]
        if not self.is_findable_object(self.template):
            raise ValueError(f"Selected object {type(self.template)} must be one of {self.FINDABLE_OBJECTS}.")
        self.shape = Shape(self.template, include_handles=self.include_handles)
        logging.debug(f"template: {self.template.tostring()}\n{self.shape.points}")

        # cache this transform: move template to rendered location, then center it
        # note: transforms are applied right to left
        translate_to_center = self.shape.center()
        self.template_transform = translate_to_center @ self.shape.render_transform

        # find objects in file that match template
        for child in self.svg.descendants():
            # don't match template to itself
            if child == self.template or not self.is_findable_object(child):
                continue

            logging.debug(f'comparing... {child.get_id()} {type(child)}')
            transform = self.match_object(child)
            if transform is None:
                transform = self.match_object(child, reverse_path=True)
            if transform is None:
            # no match
                continue

            # copy template to match
            if self.options.replace:
                container = child.getparent() if self.copy_to_parent else self.get_container()
                container.bake_transforms_recursively()
                logging.debug(f'copy {child.get_id()} to {container.get_id()}')

                copy = self.copy(container, transform, clone=self.do_clone)
                if self.copy_to_parent:
                    self.svg.selection.add(copy.get_id())

            # delete match
            if self.options.delete:
                child.getparent().remove(child)
            else:
                self.svg.selection.add(child.get_id())


if __name__ == "__main__":
    logging.basicConfig(filename='debug-log-findshape.txt', filemode='w', format='%(levelname)s: %(message)s', level=logging.DEBUG)
    logging.debug(f'python exec: {sys.executable}')
    logging.debug(f'cwd: {os.getcwd()}')
    logging.debug(f'cmd args: {sys.argv}')
    FindShape().run()

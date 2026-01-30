# Find Shape

Inkscape extension to find similar or identical shapes in a SVG document.


## Development

Run `findshape.py --version` to get the current version.

Run the following to validate the extension XML:
```
curl https://gitlab.com/inkscape/extensions/-/raw/master/inkex/tester/inkscape.extension.rng -o inkscape.extension.rng
jing inkscape.extension.rng findshape.inx
```

To make a downloadable zip file of the extension, run:
```
zip findshape.zip findshape.inx findshape.py LICENSE README.md
```


### Issues

To do:
- display error message if no template was selected, info message for how many shapes were found
- option to move matched objects to a target location (new group or layer)
- use invariant to find equivalent paths with different node orderings (cycled and/or reversed)
- add options to find different node orderings: checkbox to allow any starting node (for closed paths), checkbox to allow reversed order
- use whitening to find arbitrarily rescaled/sheared
- modify orthogonal procrustes to find rotated only (no flip)
- change find options to reflect valid transforms: none, rotate, rotate/flip, resize, resize/rotate, resize/rotate/flip, any transform
- allow template to be any number of nested elements, as long as they contain only a single connected path

Not implemented:
- only works on shapes with a single subpath (e.g. no holes), to allow multiple subpaths one will need a way to canonically order their points

Bugs
- closed paths whose nodes are cycled (i.e. the starting node is different) are not considered equivalent (will be fixed when invariant is implemented)
- has trouble comparing arcs (e.g. in ellipses), may need to change from comparing CubicSuperPath to comparing by line/arc/curve commands
- unable to add matches and copied elements to the current selection

Not a bug:
- paths with 2 nodes are ambiguous without considering handles, and may be flipped
- paths with 3 nodes will be ambiguous if not considering handles and applying whitening


## How It Works


### TL;DR

Select an object in Inkscape as the **template**.
Run the extension to find similar shapes in the document.
An object **matches** the template if its path (nodes and handles) is close enough to the template's (below a user-supplied threshold).
The user can choose if objects with different sizes, rotations, node orderings, etc. should be matching.
The match can be put into a group or deleted, and the template can be copied to the location of each match.


### The Long Technical Version

Alignment is done two ways. First, each shape can be transformed into a standard (canonical) version:
- *center* to remove translations
- *normalize* to remove resizing
- *whiten* to remove all transforms except rotation (e.g. shear transforms)

Any combination of these operations can be applied to selectively ignore some transformations: e.g. we can match objects of the same size but different orientations, or objects of different sizes and the same orientation.

There are some transforms that have no canonical version.
These need to be compared relative to the template object:
- The node order in a path can be reversed.
- For closed paths, any node can be the starting node.
- Objects can be rotated at any angle.

To speed up computations, objects are compared via an *invariant* quantity instead of their paths.
The invariant is a mathematical quantity that is unchanged by (most) transformations, but also different for (most) dissimilar objects,
and the difference between two invariants is (approximately) the difference between the original objects.
More precisely, two objects *A* and *B* with *d* dissimilarity have invariants that differ by at most *f(A, B, d)* for a function *f*.
If the invariants are far apart, the objects are guaranteed to be dissimilar, allowing us to quickly filter out objects that do not match.

This extension uses the polygon invariant defined in a paper by Luque-Suarez, López-López., & Chavez  [1], but with some modifications.
TODO discuss modifications

Since the invariant does not give a rotation to align the two objects (it is invariant to rotations, after all), we use the *orthogonal procrustes* transform to find a rotation or flip (mirroring) to align the objects as close together as possible.

To compare the template with an object:
1. Apply pre-existing transforms from the document to the template and target. This ensures we are comparing the actual shapes rendered on screen.
2. Transform both template and target to their canonical form.
3. Compute the invariant from [1].
4. Transform the target's invariant to compare different node orderings. Filter by distance to the template's invariant to get candidate versions of the target.
5. For each candidate target, rotate the target to the template using the *orthogonal procrustes* transform.
6. Calculate the distance between the template and each candidate's nodes. Take the candidate with the smallest distance - if it is below a given threshold, the target is a **match**.

To copy the template to the location and orientation of a match, build (compose) a transform in the following order:
1. Apply the template's pre-existing transforms from the document.
2. Apply the template's canonical transforms.
3. Apply the rotation aligning canonical template to canonical target.
4. Undo (apply the inverse) of the target's canonical transforms.

[1] Luque-Suarez, F., López-López, J. L., & Chavez, E. (2021, September). Indexed polygon matching under similarities. In International Conference on Similarity Search and Applications (pp. 295-306). Cham: Springer International Publishing.

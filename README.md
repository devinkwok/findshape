### Find Shape

Inkscape extension to find similar or identical shapes in a SVG document.

### Issues

Not implemented:
- find arbitrarily rescaled
- find equivalent paths with different node orderings
- change find options:
    - radio buttons: no rotate, rotate only, rotate and flip
    - radio buttons: no scale, uniform (aspect ratio preserving) rescale, arbitrary rescale
    - order of nodes for closed paths: checkbox for allow any starting node, checkbox for allow reversed order
- only works on shapes with a single subpath (e.g. no holes)

Bugs
- has trouble comparing arcs (e.g. in ellipses), may need to change from comparing CubicSuperPath to comparing by line/arc/curve commands
- matches and copied elements aren't being added to the current selection
- closed paths whose nodes are cycled (i.e. the starting node is different) are not considered equivalent

Not a bug:
- paths with 2 nodes are ambiguous without considering handles, and may be flipped

### Find Shape

Inkscape extension to find similar or identical shapes in a SVG document.

### Issues

Not implemented:
- match both nodes and handles
- find arbitrarily rescaled
- find equivalent paths with different node orderings
- change find options:
    - radio buttons: no rotate, rotate only, rotate and flip
    - radio buttons: no scale, uniform (aspect ratio preserving) rescale, arbitrary rescale
    - order of nodes for closed paths: checkbox for allow any starting node, checkbox for allow reversed order

Bugs
- ellipses are compared by their control points instead of by their equivalent path nodes
- matches and copied elements aren't being added to the current selection
- closed paths whose nodes are cycled (i.e. the starting node is different) are not considered equivalent

Not a bug:
- paths with 2 nodes are ambiguous without considering handles, and may be flipped

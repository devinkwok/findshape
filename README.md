### Find Shape

Inkscape extension to find similar or identical shapes in a SVG document.

### Issues

Not implemented:
- match nodes and handles
- find rescaled
- find sheared
- find flipped without rotation
- find rotated without flipping
- copy as duplicate

Bugs
- ellipses are compared by their control points instead of by their equivalent path nodes
- when copying to same parent as match, need to undo transforms belonging to the parent groups or layers
- matches and copied elements aren't being added to the current selection
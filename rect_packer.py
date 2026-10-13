"""
Port of Jukka Jylänki's MaxRectsBinPack algorithm.
Original C++ version released to Public Domain.
"""

from typing import List

class Rect:
    def __init__(self, x: int = 0, y: int = 0, width: int = 0, height: int = 0):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

    def __repr__(self):
        return f"Rect(x={self.x}, y={self.y}, w={self.width}, h={self.height})"

class MaxRectsBinPack:
    class FreeRectChoiceHeuristic:
        RectBestShortSideFit = 0
        RectBestLongSideFit = 1
        RectBestAreaFit = 2
        RectBottomLeftRule = 3
        RectContactPointRule = 4

    def __init__(self, width: int = 0, height: int = 0, allow_flip: bool = True):
        self.bin_width = 0
        self.bin_height = 0
        self.allow_flip = allow_flip
        self.used_rectangles: List[Rect] = []
        self.free_rectangles: List[Rect] = []
        self.init(width, height, allow_flip)

    def init(self, width: int, height: int, allow_flip: bool = True):
        self.bin_width = width
        self.bin_height = height
        self.allow_flip = allow_flip
        self.used_rectangles = []
        self.free_rectangles = []
        self.free_rectangles.append(Rect(0, 0, width, height))

    def insert(self, width: int, height: int, method: int) -> Rect:
        if method == self.FreeRectChoiceHeuristic.RectBestShortSideFit:
            new_node = self._find_position_for_new_node_best_short_side_fit(width, height)
        elif method == self.FreeRectChoiceHeuristic.RectBottomLeftRule:
            new_node = self._find_position_for_new_node_bottom_left(width, height)
        elif method == self.FreeRectChoiceHeuristic.RectContactPointRule:
            new_node = self._find_position_for_new_node_contact_point(width, height)
        elif method == self.FreeRectChoiceHeuristic.RectBestLongSideFit:
            new_node = self._find_position_for_new_node_best_long_side_fit(width, height)
        elif method == self.FreeRectChoiceHeuristic.RectBestAreaFit:
            new_node = self._find_position_for_new_node_best_area_fit(width, height)
        else:
            raise ValueError("Unknown heuristic method")

        if new_node.height == 0:
            return new_node

        self._place_rect(new_node)
        return new_node
    
    def _place_rect(self, node: Rect):
        num_rects_to_process = len(self.free_rectangles)
        i = 0
        while i < num_rects_to_process:
            if self._split_free_node(self.free_rectangles[i], node):
                self.free_rectangles.pop(i)
                num_rects_to_process -= 1
            else:
                i += 1
        
        self._prune_free_list()
        self.used_rectangles.append(node)

    def _find_position_for_new_node_bottom_left(self, width: int, height: int) -> Rect:
        best_node = Rect()
        best_y = float('inf')
        best_x = float('inf')

        for free_rect in self.free_rectangles:
            # Try to place the rectangle in upright (non-flipped) orientation.
            if free_rect.width >= width and free_rect.height >= height:
                top_side_y = free_rect.y + height
                if top_side_y < best_y or (top_side_y == best_y and free_rect.x < best_x):
                    best_node.x = free_rect.x
                    best_node.y = free_rect.y
                    best_node.width = width
                    best_node.height = height
                    best_y = top_side_y
                    best_x = free_rect.x

            if self.allow_flip and free_rect.width >= height and free_rect.height >= width:
                top_side_y = free_rect.y + width
                if top_side_y < best_y or (top_side_y == best_y and free_rect.x < best_x):
                    best_node.x = free_rect.x
                    best_node.y = free_rect.y
                    best_node.width = height
                    best_node.height = width
                    best_y = top_side_y
                    best_x = free_rect.x
        return best_node

    def _find_position_for_new_node_best_short_side_fit(self, width: int, height: int) -> Rect:
        best_node = Rect()
        best_short_side_fit = float('inf')
        best_long_side_fit = float('inf')

        for free_rect in self.free_rectangles:
            # Try to place the rectangle in upright (non-flipped) orientation.
            if free_rect.width >= width and free_rect.height >= height:
                leftover_horiz = abs(free_rect.width - width)
                leftover_vert = abs(free_rect.height - height)
                short_side_fit = min(leftover_horiz, leftover_vert)
                long_side_fit = max(leftover_horiz, leftover_vert)

                if short_side_fit < best_short_side_fit or (short_side_fit == best_short_side_fit and long_side_fit < best_long_side_fit):
                    best_node.x = free_rect.x
                    best_node.y = free_rect.y
                    best_node.width = width
                    best_node.height = height
                    best_short_side_fit = short_side_fit
                    best_long_side_fit = long_side_fit

            if self.allow_flip and free_rect.width >= height and free_rect.height >= width:
                flipped_leftover_horiz = abs(free_rect.width - height)
                flipped_leftover_vert = abs(free_rect.height - width)
                short_side_fit = min(flipped_leftover_horiz, flipped_leftover_vert)
                long_side_fit = max(flipped_leftover_horiz, flipped_leftover_vert)

                if short_side_fit < best_short_side_fit or (short_side_fit == best_short_side_fit and long_side_fit < best_long_side_fit):
                    best_node.x = free_rect.x
                    best_node.y = free_rect.y
                    best_node.width = height
                    best_node.height = width
                    best_short_side_fit = short_side_fit
                    best_long_side_fit = long_side_fit
        
        return best_node

    def _find_position_for_new_node_best_long_side_fit(self, width: int, height: int) -> Rect:
        best_node = Rect()
        best_short_side_fit = float('inf')
        best_long_side_fit = float('inf')

        for free_rect in self.free_rectangles:
            if free_rect.width >= width and free_rect.height >= height:
                leftover_horiz = abs(free_rect.width - width)
                leftover_vert = abs(free_rect.height - height)
                short_side_fit = min(leftover_horiz, leftover_vert)
                long_side_fit = max(leftover_horiz, leftover_vert)

                if long_side_fit < best_long_side_fit or (long_side_fit == best_long_side_fit and short_side_fit < best_short_side_fit):
                    best_node.x = free_rect.x
                    best_node.y = free_rect.y
                    best_node.width = width
                    best_node.height = height
                    best_short_side_fit = short_side_fit
                    best_long_side_fit = long_side_fit

            if self.allow_flip and free_rect.width >= height and free_rect.height >= width:
                leftover_horiz = abs(free_rect.width - height)
                leftover_vert = abs(free_rect.height - width)
                short_side_fit = min(leftover_horiz, leftover_vert)
                long_side_fit = max(leftover_horiz, leftover_vert)

                if long_side_fit < best_long_side_fit or (long_side_fit == best_long_side_fit and short_side_fit < best_short_side_fit):
                    best_node.x = free_rect.x
                    best_node.y = free_rect.y
                    best_node.width = height
                    best_node.height = width
                    best_short_side_fit = short_side_fit
                    best_long_side_fit = long_side_fit
        return best_node

    def _find_position_for_new_node_best_area_fit(self, width: int, height: int) -> Rect:
        best_node = Rect()
        best_area_fit = float('inf')
        best_short_side_fit = float('inf')

        for free_rect in self.free_rectangles:
            area_fit = free_rect.width * free_rect.height - width * height

            if free_rect.width >= width and free_rect.height >= height:
                leftover_horiz = abs(free_rect.width - width)
                leftover_vert = abs(free_rect.height - height)
                short_side_fit = min(leftover_horiz, leftover_vert)

                if area_fit < best_area_fit or (area_fit == best_area_fit and short_side_fit < best_short_side_fit):
                    best_node.x = free_rect.x
                    best_node.y = free_rect.y
                    best_node.width = width
                    best_node.height = height
                    best_short_side_fit = short_side_fit
                    best_area_fit = area_fit

            if self.allow_flip and free_rect.width >= height and free_rect.height >= width:
                leftover_horiz = abs(free_rect.width - height)
                leftover_vert = abs(free_rect.height - width)
                short_side_fit = min(leftover_horiz, leftover_vert)

                if area_fit < best_area_fit or (area_fit == best_area_fit and short_side_fit < best_short_side_fit):
                    best_node.x = free_rect.x
                    best_node.y = free_rect.y
                    best_node.width = height
                    best_node.height = width
                    best_short_side_fit = short_side_fit
                    best_area_fit = area_fit
        return best_node

    def _find_position_for_new_node_contact_point(self, width: int, height: int) -> Rect:
        best_node = Rect()
        best_contact_score = -1

        for free_rect in self.free_rectangles:
            if free_rect.width >= width and free_rect.height >= height:
                score = self._contact_point_score_node(free_rect.x, free_rect.y, width, height)
                if score > best_contact_score:
                    best_node.x = free_rect.x
                    best_node.y = free_rect.y
                    best_node.width = width
                    best_node.height = height
                    best_contact_score = score
            
            if self.allow_flip and free_rect.width >= height and free_rect.height >= width:
                score = self._contact_point_score_node(free_rect.x, free_rect.y, height, width)
                if score > best_contact_score:
                    best_node.x = free_rect.x
                    best_node.y = free_rect.y
                    best_node.width = height
                    best_node.height = width
                    best_contact_score = score
        return best_node

    def _contact_point_score_node(self, x: int, y: int, width: int, height: int) -> int:
        score = 0
        if x == 0 or x + width == self.bin_width:
            score += height
        if y == 0 or y + height == self.bin_height:
            score += width
        
        for r in self.used_rectangles:
            if r.x == x + width or r.x + r.width == x:
                score += self._common_interval_length(r.y, r.y + r.height, y, y + height)
            if r.y == y + height or r.y + r.height == y:
                score += self._common_interval_length(r.x, r.x + r.width, x, x + width)
        return score

    def _common_interval_length(self, i1start: int, i1end: int, i2start: int, i2end: int) -> int:
        if i1end < i2start or i2end < i1start:
            return 0
        return min(i1end, i2end) - max(i1start, i2start)

    def _split_free_node(self, free_node: Rect, used_node: Rect) -> bool:
        # Test if rectangles intersect
        if (used_node.x >= free_node.x + free_node.width or used_node.x + used_node.width <= free_node.x or
                used_node.y >= free_node.y + free_node.height or used_node.y + used_node.height <= free_node.y):
            return False

        if used_node.x < free_node.x + free_node.width and used_node.x + used_node.width > free_node.x:
            # New node at the top side of the used node.
            if used_node.y > free_node.y and used_node.y < free_node.y + free_node.height:
                new_node = Rect(free_node.x, free_node.y, free_node.width, used_node.y - free_node.y)
                self.free_rectangles.append(new_node)

            # New node at the bottom side of the used node.
            if used_node.y + used_node.height < free_node.y + free_node.height:
                new_node = Rect(free_node.x, used_node.y + used_node.height, free_node.width, 
                                free_node.y + free_node.height - (used_node.y + used_node.height))
                self.free_rectangles.append(new_node)

        if used_node.y < free_node.y + free_node.height and used_node.y + used_node.height > free_node.y:
            # New node at the left side of the used node.
            if used_node.x > free_node.x and used_node.x < free_node.x + free_node.width:
                new_node = Rect(free_node.x, free_node.y, used_node.x - free_node.x, free_node.height)
                self.free_rectangles.append(new_node)

            # New node at the right side of the used node.
            if used_node.x + used_node.width < free_node.x + free_node.width:
                new_node = Rect(used_node.x + used_node.width, free_node.y, 
                                free_node.x + free_node.width - (used_node.x + used_node.width), free_node.height)
                self.free_rectangles.append(new_node)
        
        return True

    def _prune_free_list(self):
        # Go through free list and remove contained rects
        # This is n^2 basic implementation, can be optimized but likely fine for typical texture atlases
        i = 0
        while i < len(self.free_rectangles):
            j = i + 1
            while j < len(self.free_rectangles):
                if self._is_contained_in(self.free_rectangles[i], self.free_rectangles[j]):
                    self.free_rectangles.pop(i)
                    i -= 1
                    break
                if self._is_contained_in(self.free_rectangles[j], self.free_rectangles[i]):
                    self.free_rectangles.pop(j)
                    j -= 1
                j += 1
            i += 1

    def _is_contained_in(self, a: Rect, b: Rect) -> bool:
        return (a.x >= b.x and a.y >= b.y and 
                a.x + a.width <= b.x + b.width and 
                a.y + a.height <= b.y + b.height)

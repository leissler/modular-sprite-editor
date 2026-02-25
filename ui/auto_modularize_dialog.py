import wx

from optimization import get_auto_modularization_platform_profiles


class AutoModularizeDialog(wx.Dialog):
    def __init__(self, parent, show_grid_options=False):
        super().__init__(parent, title="Auto Modularize Spritesheet")

        def set_tip(*controls, text):
            for ctrl in controls:
                ctrl.SetToolTip(text)

        self._profiles = get_auto_modularization_platform_profiles()
        self._profile_keys = list(self._profiles.keys())

        sizer = wx.BoxSizer(wx.VERTICAL)

        sb_mode = wx.StaticBoxSizer(wx.VERTICAL, self, "Mode")
        mode_grid = wx.FlexGridSizer(rows=0, cols=2, vgap=6, hgap=10)
        mode_grid.AddGrowableCol(1, 1)

        lbl_mode = wx.StaticText(self, label="Modularization Mode")
        mode_grid.Add(lbl_mode, 0, wx.ALIGN_CENTER_VERTICAL)
        self.choice_mode = wx.Choice(self, choices=["Freeform (Current)", "Tile-Constrained"])
        self.choice_mode.SetSelection(0)
        mode_grid.Add(self.choice_mode, 0, wx.EXPAND)
        set_tip(
            lbl_mode,
            self.choice_mode,
            text=(
                "Freeform keeps the existing pixel-space decomposition behavior.\n"
                "Tile-constrained snaps decomposition to a tile grid and applies profile constraints."
            ),
        )

        lbl_profile = wx.StaticText(self, label="Platform Profile")
        mode_grid.Add(lbl_profile, 0, wx.ALIGN_CENTER_VERTICAL)
        profile_labels = [self._profiles[k].get("label", k) for k in self._profile_keys]
        self.choice_profile = wx.Choice(self, choices=profile_labels)
        self.choice_profile.SetSelection(0)
        mode_grid.Add(self.choice_profile, 0, wx.EXPAND)
        set_tip(
            lbl_profile,
            self.choice_profile,
            text=(
                "Applies platform-aware defaults for tile size, meta-tiles, palette rules, and flip capabilities."
            ),
        )

        sb_mode.Add(mode_grid, 0, wx.EXPAND | wx.ALL, 8)
        sizer.Add(sb_mode, 0, wx.EXPAND | wx.ALL, 10)

        sb_tile = wx.StaticBoxSizer(wx.VERTICAL, self, "Tile Constraints")
        tile_grid = wx.FlexGridSizer(rows=0, cols=2, vgap=6, hgap=10)
        tile_grid.AddGrowableCol(1, 1)

        lbl_tile_w = wx.StaticText(self, label="Tile Width")
        tile_grid.Add(lbl_tile_w, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_tile_w = wx.SpinCtrl(self, min=1, max=128, initial=8)
        tile_grid.Add(self.spin_tile_w, 0, wx.EXPAND)

        lbl_tile_h = wx.StaticText(self, label="Tile Height")
        tile_grid.Add(lbl_tile_h, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_tile_h = wx.SpinCtrl(self, min=1, max=128, initial=8)
        tile_grid.Add(self.spin_tile_h, 0, wx.EXPAND)

        lbl_meta_mode = wx.StaticText(self, label="Meta-Tile Mode")
        tile_grid.Add(lbl_meta_mode, 0, wx.ALIGN_CENTER_VERTICAL)
        self.choice_meta_mode = wx.Choice(self, choices=["Off", "Prefer", "Force"])
        self.choice_meta_mode.SetSelection(1)
        tile_grid.Add(self.choice_meta_mode, 0, wx.EXPAND)
        set_tip(
            lbl_meta_mode,
            self.choice_meta_mode,
            text=(
                "Off: ignore meta-tiles. Prefer: use when scoring helps. Force: prioritize meta-tiles first."
            ),
        )

        lbl_meta_sizes = wx.StaticText(self, label="Meta-Tile Sizes")
        tile_grid.Add(lbl_meta_sizes, 0, wx.ALIGN_CENTER_VERTICAL)
        self.choice_meta_sizes = wx.Choice(
            self,
            choices=[
                "None",
                "16x16",
                "16x16 + 32x32",
                "32x32",
            ],
        )
        self.choice_meta_sizes.SetSelection(2)
        tile_grid.Add(self.choice_meta_sizes, 0, wx.EXPAND)
        set_tip(
            lbl_meta_sizes,
            self.choice_meta_sizes,
            text=(
                "Optional grouping above base tiles. Useful for retro workflows with 16x16 or 32x32 map chunks."
            ),
        )

        lbl_sparse = wx.StaticText(self, label="Sparse Tile Threshold %")
        tile_grid.Add(lbl_sparse, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_sparse_threshold = wx.SpinCtrl(self, min=0, max=100, initial=35)
        tile_grid.Add(self.spin_sparse_threshold, 0, wx.EXPAND)
        set_tip(
            lbl_sparse,
            self.spin_sparse_threshold,
            text=(
                "Tiles under this opacity density are considered sparse.\n"
                "Sparse tiles are grouped with diagonal-aware logic to reduce fragmentation."
            ),
        )

        self.chk_palette_constraints = wx.CheckBox(self, label="Enforce Palette/Attribute Constraints")
        self.chk_palette_constraints.SetValue(False)
        sb_tile.Add(tile_grid, 0, wx.EXPAND | wx.ALL, 8)
        sb_tile.Add(self.chk_palette_constraints, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        palette_grid = wx.FlexGridSizer(rows=0, cols=2, vgap=6, hgap=10)
        palette_grid.AddGrowableCol(1, 1)

        lbl_colors = wx.StaticText(self, label="Max Colors Per Tile")
        palette_grid.Add(lbl_colors, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_tile_colors = wx.SpinCtrl(self, min=1, max=64, initial=16)
        palette_grid.Add(self.spin_tile_colors, 0, wx.EXPAND)

        lbl_attr_w = wx.StaticText(self, label="Attribute Block Width (tiles)")
        palette_grid.Add(lbl_attr_w, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_attr_w = wx.SpinCtrl(self, min=1, max=8, initial=1)
        palette_grid.Add(self.spin_attr_w, 0, wx.EXPAND)

        lbl_attr_h = wx.StaticText(self, label="Attribute Block Height (tiles)")
        palette_grid.Add(lbl_attr_h, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_attr_h = wx.SpinCtrl(self, min=1, max=8, initial=1)
        palette_grid.Add(self.spin_attr_h, 0, wx.EXPAND)

        lbl_attr_pal = wx.StaticText(self, label="Max Palettes Per Attribute Block")
        palette_grid.Add(lbl_attr_pal, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_attr_palettes = wx.SpinCtrl(self, min=1, max=8, initial=1)
        palette_grid.Add(self.spin_attr_palettes, 0, wx.EXPAND)

        sb_tile.Add(palette_grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        flip_row = wx.BoxSizer(wx.HORIZONTAL)
        self.chk_tile_flip_x = wx.CheckBox(self, label="Allow Horizontal Flip Dedup")
        self.chk_tile_flip_x.SetValue(True)
        flip_row.Add(self.chk_tile_flip_x, 0, wx.RIGHT, 12)
        self.chk_tile_flip_y = wx.CheckBox(self, label="Allow Vertical Flip (Profile Hint)")
        self.chk_tile_flip_y.SetValue(False)
        flip_row.Add(self.chk_tile_flip_y, 0)
        sb_tile.Add(flip_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        sizer.Add(sb_tile, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        sb_proc = wx.StaticBoxSizer(wx.VERTICAL, self, "Analysis")

        grid = wx.FlexGridSizer(rows=0, cols=2, vgap=6, hgap=10)
        grid.AddGrowableCol(1, 1)

        lbl_alpha = wx.StaticText(self, label="Alpha Threshold")
        grid.Add(lbl_alpha, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_alpha = wx.SpinCtrl(self, min=0, max=255, initial=0)
        grid.Add(self.spin_alpha, 0, wx.EXPAND)
        set_tip(
            lbl_alpha,
            self.spin_alpha,
            text=(
                "Pixels with alpha <= this value are treated as transparent during analysis.\n"
                "Increase to ignore faint anti-aliased edges or compression noise.\n"
                "Higher values can remove thin details."
            ),
        )

        lbl_transparent = wx.StaticText(self, label="Max Transparent %")
        grid.Add(lbl_transparent, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_transparent_pct = wx.SpinCtrl(self, min=0, max=95, initial=50)
        grid.Add(self.spin_transparent_pct, 0, wx.EXPAND)
        set_tip(
            lbl_transparent,
            self.spin_transparent_pct,
            text=(
                "Maximum transparent-pixel ratio allowed when forming or merging larger parts.\n"
                "Lower values force tighter cuts on sparse shapes (diagonals/L-shapes), usually creating more parts.\n"
                "Higher values allow larger boxes and fewer parts."
            ),
        )

        lbl_min_area = wx.StaticText(self, label="Min Part Area (px)")
        grid.Add(lbl_min_area, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_min_area = wx.SpinCtrl(self, min=1, max=4096, initial=1)
        grid.Add(self.spin_min_area, 0, wx.EXPAND)

        lbl_merge_gap = wx.StaticText(self, label="Merge Gap (px)")
        grid.Add(lbl_merge_gap, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_merge_gap = wx.SpinCtrl(self, min=0, max=16, initial=1)
        grid.Add(self.spin_merge_gap, 0, wx.EXPAND)

        lbl_min_split_side = wx.StaticText(self, label="Min Split Side")
        grid.Add(lbl_min_split_side, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_min_split_side = wx.SpinCtrl(self, min=2, max=64, initial=2)
        grid.Add(self.spin_min_split_side, 0, wx.EXPAND)

        lbl_max_split_depth = wx.StaticText(self, label="Max Split Depth")
        grid.Add(lbl_max_split_depth, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_max_split_depth = wx.SpinCtrl(self, min=1, max=20, initial=8)
        grid.Add(self.spin_max_split_depth, 0, wx.EXPAND)

        sb_proc.Add(grid, 0, wx.EXPAND | wx.ALL, 8)
        sb_proc.Add(
            wx.StaticText(
                self,
                label=(
                    "Lower Max Transparent % creates tighter cuts for sparse shapes "
                    "(L-shapes, diagonals, thin weapons)."
                ),
            ),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            8,
        )

        self.chk_pattern_mining = wx.CheckBox(
            self,
            label="Detect Reused Copy/Paste Parts (Pattern Mining)",
        )
        self.chk_pattern_mining.SetValue(True)
        sb_proc.Add(self.chk_pattern_mining, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        pattern_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_pattern_occ = wx.StaticText(self, label="Min Pattern Occurrences")
        pattern_row.Add(lbl_pattern_occ, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.spin_pattern_occ = wx.SpinCtrl(self, min=2, max=32, initial=3)
        pattern_row.Add(self.spin_pattern_occ, 0)
        sb_proc.Add(pattern_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        sizer.Add(sb_proc, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        sb_out = wx.StaticBoxSizer(wx.VERTICAL, self, "Output")
        self.chk_dedupe = wx.CheckBox(self, label="Deduplicate Identical Parts")
        self.chk_dedupe.SetValue(True)
        sb_out.Add(self.chk_dedupe, 0, wx.ALL, 5)

        self.chk_replace_refs = wx.CheckBox(self, label="Replace Frame References to Original Modules")
        self.chk_replace_refs.SetValue(True)
        sb_out.Add(self.chk_replace_refs, 0, wx.ALL, 5)

        self.chk_delete_originals = wx.CheckBox(self, label="Delete Original Modules After Split")
        self.chk_delete_originals.SetValue(True)
        sb_out.Add(self.chk_delete_originals, 0, wx.ALL, 5)

        sizer.Add(sb_out, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btns, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        self.SetSizerAndFit(sizer)
        self.CenterOnParent()

        self.choice_mode.Bind(wx.EVT_CHOICE, self._on_mode_changed)
        self.choice_profile.Bind(wx.EVT_CHOICE, self._on_profile_changed)
        self.chk_palette_constraints.Bind(wx.EVT_CHECKBOX, self._on_palette_toggle)

        self._apply_profile_defaults()
        self._refresh_mode_ui()

    def _selected_profile_key(self) -> str:
        idx = self.choice_profile.GetSelection()
        if 0 <= idx < len(self._profile_keys):
            return self._profile_keys[idx]
        return self._profile_keys[0] if self._profile_keys else "generic_8x8"

    def _on_mode_changed(self, _event: wx.CommandEvent) -> None:
        self._refresh_mode_ui()

    def _on_profile_changed(self, _event: wx.CommandEvent) -> None:
        self._apply_profile_defaults()
        self._refresh_mode_ui()

    def _on_palette_toggle(self, _event: wx.CommandEvent) -> None:
        self._refresh_mode_ui()

    def _set_meta_sizes_choice(self, sizes):
        normalized = sorted([tuple(v) for v in sizes])
        idx = 0
        if normalized == [(16, 16)]:
            idx = 1
        elif normalized == [(16, 16), (32, 32)]:
            idx = 2
        elif normalized == [(32, 32)]:
            idx = 3
        self.choice_meta_sizes.SetSelection(idx)

    def _get_meta_sizes_from_choice(self):
        sel = self.choice_meta_sizes.GetSelection()
        if sel == 1:
            return [(16, 16)]
        if sel == 2:
            return [(16, 16), (32, 32)]
        if sel == 3:
            return [(32, 32)]
        return []

    def _apply_profile_defaults(self) -> None:
        key = self._selected_profile_key()
        profile = self._profiles.get(key, {})

        self.spin_tile_w.SetValue(int(profile.get("tile_w", 8)))
        self.spin_tile_h.SetValue(int(profile.get("tile_h", 8)))

        mode = str(profile.get("meta_tile_mode", "prefer")).strip().lower()
        mode_idx = 1
        if mode == "off":
            mode_idx = 0
        elif mode == "force":
            mode_idx = 2
        self.choice_meta_mode.SetSelection(mode_idx)

        self._set_meta_sizes_choice(profile.get("meta_tile_sizes", []))
        self.spin_sparse_threshold.SetValue(int(round(float(profile.get("sparse_tile_threshold", 0.35)) * 100.0)))

        enforce_palette = (
            int(profile.get("max_colors_per_tile", 0)) > 0
            or int(profile.get("max_palettes_per_attribute_block", 0)) > 0
            or str(profile.get("palette_mode", "none")) != "none"
        )
        self.chk_palette_constraints.SetValue(enforce_palette)
        self.spin_tile_colors.SetValue(max(1, int(profile.get("max_colors_per_tile", 16) or 16)))

        block = profile.get("attribute_block_tiles", (1, 1))
        bw = int(block[0]) if isinstance(block, (tuple, list)) and len(block) >= 1 else 1
        bh = int(block[1]) if isinstance(block, (tuple, list)) and len(block) >= 2 else 1
        self.spin_attr_w.SetValue(max(1, bw))
        self.spin_attr_h.SetValue(max(1, bh))

        self.spin_attr_palettes.SetValue(max(1, int(profile.get("max_palettes_per_attribute_block", 1) or 1)))
        self.chk_tile_flip_x.SetValue(bool(profile.get("allow_flip_x", True)))
        self.chk_tile_flip_y.SetValue(bool(profile.get("allow_flip_y", False)))

    def _refresh_mode_ui(self) -> None:
        tile_mode = self.choice_mode.GetSelection() == 1

        tile_controls = [
            self.choice_profile,
            self.spin_tile_w,
            self.spin_tile_h,
            self.choice_meta_mode,
            self.choice_meta_sizes,
            self.spin_sparse_threshold,
            self.chk_palette_constraints,
            self.spin_tile_colors,
            self.spin_attr_w,
            self.spin_attr_h,
            self.spin_attr_palettes,
            self.chk_tile_flip_x,
            self.chk_tile_flip_y,
        ]
        for ctrl in tile_controls:
            ctrl.Enable(tile_mode)

        palette_enabled = tile_mode and self.chk_palette_constraints.GetValue()
        self.spin_tile_colors.Enable(palette_enabled)
        self.spin_attr_w.Enable(palette_enabled)
        self.spin_attr_h.Enable(palette_enabled)
        self.spin_attr_palettes.Enable(palette_enabled)

        freeform_controls = [
            self.spin_merge_gap,
            self.spin_min_split_side,
            self.spin_max_split_depth,
            self.chk_pattern_mining,
            self.spin_pattern_occ,
        ]
        for ctrl in freeform_controls:
            ctrl.Enable(not tile_mode)

    def GetValues(self):
        tile_mode = self.choice_mode.GetSelection() == 1
        profile_key = self._selected_profile_key()
        meta_mode_idx = self.choice_meta_mode.GetSelection()
        meta_mode = "prefer"
        if meta_mode_idx == 0:
            meta_mode = "off"
        elif meta_mode_idx == 2:
            meta_mode = "force"

        return {
            "modularization_mode": "tile_constrained" if tile_mode else "freeform",
            "platform_profile": profile_key,
            "tile_width": self.spin_tile_w.GetValue(),
            "tile_height": self.spin_tile_h.GetValue(),
            "meta_tile_mode": meta_mode,
            "meta_tile_sizes": self._get_meta_sizes_from_choice(),
            "sparse_tile_threshold": self.spin_sparse_threshold.GetValue() / 100.0,
            "tile_enforce_palette_constraints": self.chk_palette_constraints.GetValue(),
            "tile_max_colors_per_tile": self.spin_tile_colors.GetValue(),
            "tile_attribute_block_w": self.spin_attr_w.GetValue(),
            "tile_attribute_block_h": self.spin_attr_h.GetValue(),
            "tile_max_palettes_per_attribute_block": self.spin_attr_palettes.GetValue(),
            "tile_allow_flip_x": self.chk_tile_flip_x.GetValue(),
            "tile_allow_flip_y": self.chk_tile_flip_y.GetValue(),
            "alpha_threshold": self.spin_alpha.GetValue(),
            "max_transparent_ratio": self.spin_transparent_pct.GetValue() / 100.0,
            "min_part_area": self.spin_min_area.GetValue(),
            "merge_gap": self.spin_merge_gap.GetValue(),
            "min_split_side": self.spin_min_split_side.GetValue(),
            "max_split_depth": self.spin_max_split_depth.GetValue(),
            "pattern_mining": self.chk_pattern_mining.GetValue(),
            "min_pattern_occurrences": self.spin_pattern_occ.GetValue(),
            "deduplicate": self.chk_dedupe.GetValue(),
            "replace_in_frames": self.chk_replace_refs.GetValue(),
            "delete_original_modules": self.chk_delete_originals.GetValue(),
        }

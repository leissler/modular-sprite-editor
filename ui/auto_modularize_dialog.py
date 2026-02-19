import wx

class AutoModularizeDialog(wx.Dialog):
    def __init__(self, parent, show_grid_options=False):
        super().__init__(parent, title="Auto Modularize Spritesheet")

        def set_tip(*controls, text):
            for ctrl in controls:
                ctrl.SetToolTip(text)

        sizer = wx.BoxSizer(wx.VERTICAL)

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
        set_tip(
            lbl_min_area,
            self.spin_min_area,
            text=(
                "Minimum opaque-pixel budget used by split decisions.\n"
                "Higher values reduce tiny micro-parts and noise, but may keep larger combined chunks."
            ),
        )

        lbl_merge_gap = wx.StaticText(self, label="Merge Gap (px)")
        grid.Add(lbl_merge_gap, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_merge_gap = wx.SpinCtrl(self, min=0, max=16, initial=1)
        grid.Add(self.spin_merge_gap, 0, wx.EXPAND)
        set_tip(
            lbl_merge_gap,
            self.spin_merge_gap,
            text=(
                "How close two parts can be (in pixels) and still be considered for merging.\n"
                "Merges only happen when the merged box still satisfies Max Transparent %.\n"
                "Higher gap can reduce part count; lower gap keeps parts more local."
            ),
        )

        lbl_min_split_side = wx.StaticText(self, label="Min Split Side")
        grid.Add(lbl_min_split_side, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_min_split_side = wx.SpinCtrl(self, min=2, max=64, initial=2)
        grid.Add(self.spin_min_split_side, 0, wx.EXPAND)
        set_tip(
            lbl_min_split_side,
            self.spin_min_split_side,
            text=(
                "Smallest width/height the splitter is allowed to keep cutting.\n"
                "Lower values allow thinner strips and finer decomposition.\n"
                "Higher values prevent 1-2px confetti but can leave larger sparse leftovers."
            ),
        )

        lbl_max_split_depth = wx.StaticText(self, label="Max Split Depth")
        grid.Add(lbl_max_split_depth, 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_max_split_depth = wx.SpinCtrl(self, min=1, max=20, initial=8)
        grid.Add(self.spin_max_split_depth, 0, wx.EXPAND)
        set_tip(
            lbl_max_split_depth,
            self.spin_max_split_depth,
            text=(
                "Maximum recursion depth for region splitting.\n"
                "Higher values can better resolve complex diagonals and cavities, but may generate more fragments and take longer."
            ),
        )

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
        set_tip(
            self.chk_pattern_mining,
            text=(
                "Searches across modules for repeated pixel patches and reuses one shared part.\n"
                "Good for heads, limbs, weapons reused in different positions."
            ),
        )
        sb_proc.Add(self.chk_pattern_mining, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        pattern_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_pattern_occ = wx.StaticText(self, label="Min Pattern Occurrences")
        pattern_row.Add(lbl_pattern_occ, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.spin_pattern_occ = wx.SpinCtrl(self, min=2, max=32, initial=3)
        pattern_row.Add(self.spin_pattern_occ, 0)
        set_tip(
            lbl_pattern_occ,
            self.spin_pattern_occ,
            text=(
                "Minimum number of occurrences needed before a repeated patch becomes a shared module.\n"
                "Lower values find more patterns (including weaker ones); higher values keep only strong repeats."
            ),
        )
        sb_proc.Add(pattern_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        sizer.Add(sb_proc, 0, wx.EXPAND | wx.ALL, 10)

        sb_out = wx.StaticBoxSizer(wx.VERTICAL, self, "Output")
        self.chk_dedupe = wx.CheckBox(self, label="Deduplicate Identical Parts")
        self.chk_dedupe.SetValue(True)
        set_tip(
            self.chk_dedupe,
            text=(
                "If enabled, byte-identical part images share one module definition.\n"
                "Usually reduces module count without changing visuals."
            ),
        )
        sb_out.Add(self.chk_dedupe, 0, wx.ALL, 5)

        self.chk_replace_refs = wx.CheckBox(self, label="Replace Frame References to Original Modules")
        self.chk_replace_refs.SetValue(True)
        set_tip(
            self.chk_replace_refs,
            text=(
                "Rewrites existing frame module references to use the generated parts at correct offsets.\n"
                "Keep enabled if you want immediate optimization results in animations."
            ),
        )
        sb_out.Add(self.chk_replace_refs, 0, wx.ALL, 5)

        self.chk_delete_originals = wx.CheckBox(self, label="Delete Original Modules After Split")
        self.chk_delete_originals.SetValue(True)
        set_tip(
            self.chk_delete_originals,
            text=(
                "Removes original source modules after successful split.\n"
                "Disable if you want to compare old vs new modules or keep a fallback."
            ),
        )
        sb_out.Add(self.chk_delete_originals, 0, wx.ALL, 5)

        sizer.Add(sb_out, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btns, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        self.SetSizerAndFit(sizer)
        self.CenterOnParent()

    def GetValues(self):
        return {
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

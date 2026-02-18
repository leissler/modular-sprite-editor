import wx

class AutoModularizeDialog(wx.Dialog):
    def __init__(self, parent, show_grid_options=False):
        super().__init__(parent, title="Auto Modularize Spritesheet")

        sizer = wx.BoxSizer(wx.VERTICAL)

        sb_proc = wx.StaticBoxSizer(wx.VERTICAL, self, "Analysis")

        grid = wx.FlexGridSizer(rows=0, cols=2, vgap=6, hgap=10)
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(self, label="Alpha Threshold"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_alpha = wx.SpinCtrl(self, min=0, max=255, initial=0)
        grid.Add(self.spin_alpha, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Max Transparent %"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_transparent_pct = wx.SpinCtrl(self, min=0, max=95, initial=50)
        grid.Add(self.spin_transparent_pct, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Min Part Area (px)"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_min_area = wx.SpinCtrl(self, min=1, max=4096, initial=1)
        grid.Add(self.spin_min_area, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Merge Gap (px)"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_merge_gap = wx.SpinCtrl(self, min=0, max=16, initial=1)
        grid.Add(self.spin_merge_gap, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Min Split Side"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_min_split_side = wx.SpinCtrl(self, min=2, max=64, initial=2)
        grid.Add(self.spin_min_split_side, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Max Split Depth"), 0, wx.ALIGN_CENTER_VERTICAL)
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
        pattern_row.Add(wx.StaticText(self, label="Min Pattern Occurrences"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.spin_pattern_occ = wx.SpinCtrl(self, min=2, max=32, initial=3)
        pattern_row.Add(self.spin_pattern_occ, 0)
        sb_proc.Add(pattern_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        sizer.Add(sb_proc, 0, wx.EXPAND | wx.ALL, 10)

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

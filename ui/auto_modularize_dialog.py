import wx

class AutoModularizeDialog(wx.Dialog):
    def __init__(self, parent, show_grid_options=True):
        super().__init__(parent, title="Auto-Modularize & Optimize")
        
        self.show_grid_options = show_grid_options
        
        # Defaults
        self.rows = 1
        self.cols = 1
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # --- Source Section ---
        if self.show_grid_options:
            sb_source = wx.StaticBoxSizer(wx.VERTICAL, self, "1. Source (Grid Slicing)")
            
            grid_sizer = wx.FlexGridSizer(2, 4, 5, 10)
            
            grid_sizer.Add(wx.StaticText(self, label="Rows:"), 0, wx.ALIGN_CENTER_VERTICAL)
            self.spin_rows = wx.SpinCtrl(self, min=1, max=128, initial=1)
            grid_sizer.Add(self.spin_rows)
            
            grid_sizer.Add(wx.StaticText(self, label="Columns:"), 0, wx.ALIGN_CENTER_VERTICAL)
            self.spin_cols = wx.SpinCtrl(self, min=1, max=128, initial=1)
            grid_sizer.Add(self.spin_cols)
            
            sb_source.Add(grid_sizer, 0, wx.ALL, 5)
            sb_source.Add(wx.StaticText(self, label="Use this to slice a sprite sheet into initial frames."), 0, wx.ALL, 5)
            
            sizer.Add(sb_source, 0, wx.EXPAND | wx.ALL, 10)
        
        # --- Processing Section ---
        sb_proc = wx.StaticBoxSizer(wx.VERTICAL, self, "2. Processing (Decomposition)")
        
        # Method
        self.rb_method = wx.RadioBox(self, label="Decomposition Method", 
                                     choices=["Simple Trim (Bounding Box)", "Recursive XY-Cut (Standard)", "Greedy Maximal Rects (Aggressive)"],
                                     majorDimension=1, style=wx.RA_SPECIFY_COLS)
        sb_proc.Add(self.rb_method, 0, wx.EXPAND | wx.ALL, 5)
        
        # Tolerance
        tol_sizer = wx.BoxSizer(wx.HORIZONTAL)
        tol_sizer.Add(wx.StaticText(self, label="Tolerance (Hole Filling):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.spin_tol = wx.SpinCtrl(self, min=0, max=10, initial=0)
        tol_sizer.Add(self.spin_tol, 0)
        tol_sizer.Add(wx.StaticText(self, label="px"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        
        sb_proc.Add(tol_sizer, 0, wx.ALL, 5)
        sb_proc.Add(wx.StaticText(self, label="Higher tolerance ignores small gaps (0 = Exact)."), 0, wx.LEFT | wx.BOTTOM, 5)
        
        # Common Parts
        self.chk_common = wx.CheckBox(self, label="Extract Static Backgrounds (Common Parts)")
        self.chk_common.SetToolTip("Detects parts that are identical across frames (e.g. static body) and extracts them as single modules.")
        sb_proc.Add(self.chk_common, 0, wx.ALL, 5)
        
        # Dedupe
        self.chk_dedupe = wx.CheckBox(self, label="Deduplicate Parts")
        self.chk_dedupe.SetValue(True)
        sb_proc.Add(self.chk_dedupe, 0, wx.ALL, 5)

        sizer.Add(sb_proc, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        # --- Output Section ---
        sb_out = wx.StaticBoxSizer(wx.VERTICAL, self, "3. Output")
        self.chk_optimize = wx.CheckBox(self, label="Run Optimizer (Pack into new sheet)")
        self.chk_optimize.SetValue(True)
        sb_out.Add(self.chk_optimize, 0, wx.ALL, 5)
        
        sizer.Add(sb_out, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        # Buttons
        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btns, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
        
        self.SetSizerAndFit(sizer)
        self.CenterOnParent()
        
    def GetValues(self):
        vals = {
            "method": ["trim", "xy_cut", "greedy"][self.rb_method.GetSelection()],
            "tolerance": self.spin_tol.GetValue(),
            "extract_common": self.chk_common.GetValue(),
            "deduplicate": self.chk_dedupe.GetValue(),
            "optimize": self.chk_optimize.GetValue()
        }
        if self.show_grid_options:
            vals["rows"] = self.spin_rows.GetValue()
            vals["cols"] = self.spin_cols.GetValue()
        return vals

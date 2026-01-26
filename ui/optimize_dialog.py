import wx

class OptimizeDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Optimize Sprite Sheet")

        self.padding = 2
        self.max_w = 2048
        self.max_h = 2048
        self.border_padding = 2
        self.allow_rotation = False

        sizer = wx.BoxSizer(wx.VERTICAL)

        # Padding
        row1 = wx.BoxSizer(wx.HORIZONTAL)
        row1.Add(wx.StaticText(self, label="Inner Padding:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.spin_padding = wx.SpinCtrl(self, min=0, max=128, initial=self.padding)
        row1.Add(self.spin_padding, 0)
        sizer.Add(row1, 0, wx.EXPAND | wx.ALL, 10)
        
        # Border Padding
        row_border = wx.BoxSizer(wx.HORIZONTAL)
        row_border.Add(wx.StaticText(self, label="Border Padding:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.spin_border_padding = wx.SpinCtrl(self, min=0, max=128, initial=self.border_padding)
        row_border.Add(self.spin_border_padding, 0)
        sizer.Add(row_border, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Max Dimensions
        row2 = wx.BoxSizer(wx.HORIZONTAL)
        row2.Add(wx.StaticText(self, label="Max Width:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.spin_w = wx.SpinCtrl(self, min=64, max=8192, initial=self.max_w)
        row2.Add(self.spin_w, 0, wx.RIGHT, 15)
        
        row2.Add(wx.StaticText(self, label="Max Height:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.spin_h = wx.SpinCtrl(self, min=64, max=8192, initial=self.max_h)
        row2.Add(self.spin_h, 0)
        sizer.Add(row2, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Rotation
        self.chk_rotation = wx.CheckBox(self, label="Allow Rotation (Advanced)")
        self.chk_rotation.SetToolTip("Warning: Requires engine support to handle rotated module regions.")
        sizer.Add(self.chk_rotation, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Buttons
        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        self.SetSizerAndFit(sizer)
        self.CenterOnParent()

    def GetValues(self):
        return {
            "padding": self.spin_padding.GetValue(),
            "border_padding": self.spin_border_padding.GetValue(),
            "max_w": self.spin_w.GetValue(),
            "max_h": self.spin_h.GetValue(),
            "allow_rotation": self.chk_rotation.GetValue()
        }

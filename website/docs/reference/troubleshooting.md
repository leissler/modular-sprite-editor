# Troubleshooting

## The editor does not start

On macOS and Windows, the first start of an unsigned app needs one extra confirmation. [Get the editor](../start/install.md) explains it for each system. On Linux, check that your system is recent enough, for example Ubuntu 22.04 or newer.

## The editor quit unexpectedly

Start it again. It offers to restore the changes you had not saved, as they were at most half a minute before it quit. **Restore** opens them as an unsaved project: save to keep them. **Later** asks again at the next start, **Discard** throws them away.

## A project does not open

If a project file is damaged, the version before the last save is next to it as `name.json.bak`. Make a copy of it, remove `.bak` from the copy's name and open the copy.

## An image is missing

The image file was moved or renamed after it was added. Select it in the **Images** list of the **Modules** tab and choose **Locate...** in the inspector. Keep images next to the project file, or in a folder below it, so the project finds them on another computer too.

## Parts are missing or look different everywhere

Check **Preview mapping** at the top of the window. A mapping can hide or replace parts in every tab. Set it to **<none>** to see the original modules.

## A swapped part sits in the wrong place

Parts are placed by their **pivot**. When you swap a module for another one, in a frame or with a mapping, the new module lands with its pivot where the old pivot was. Give modules that replace each other their pivot at the same spot, for example at the neck for heads. See [Names and pivots](../guide/modules.md#names-and-pivots).

## An animation plays too fast or too slow

Check **Tick rate** in the inspector of the **Animations** tab, and the holds of the steps. **Speed** in the transport only changes the preview, not the animation.

## "Then play" never starts

The animation never ends, so nothing can follow it. Choose **Play once**, or give a repeating animation a **Repeat** count. The inspector shows a warning while this is the case.

## The budget overlay shows red lines

Too many hardware sprites meet on those lines, and on the console some would disappear. [Stay within the console's limits](../guide/hardware-budget.md) has tips for bringing the number down.

## Keys do nothing

Shortcuts go to a canvas only while you are not typing in a text field. Click the canvas, then try again.

## The project warns that it was made with a newer version

The project was saved by a newer editor. You can open it, but details the older version does not know about may be lost when you save. Update the editor instead; see [Updating](../start/install.md#updating).

## Something else

[Get help](support.md) explains how to report a problem.

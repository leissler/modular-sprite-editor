using System.Collections.Generic;
using UnityEngine;

// What a game's script does with the exported events: implement OnSpriteEvent.
public class EventProbe : MonoBehaviour
{
    public static readonly List<string> Fired = new List<string>();
    public void OnSpriteEvent(AnimationEvent e) { Fired.Add(e.stringParameter + ":" + e.intParameter); }
}

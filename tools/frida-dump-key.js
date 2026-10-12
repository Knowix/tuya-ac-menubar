// Dump Tuya device id + local key from a running Tuya-SDK Android app
// (Smart Life, or a vendor app such as Sendo Smart) with Frida — no cloud
// account needed. This is the method used to recover the Sendo key.
//
// Prerequisites
//   - A rooted device or emulator (e.g. an Android Studio AVD) with the app
//     installed AND logged in (the device list must have loaded at least once).
//   - frida-server running on the device. USE FRIDA 16.x: frida 17 removed the
//     built-in `Java` bridge this script relies on.
//       pip install "frida-tools==12.*" "frida==16.*"
//       # push the matching frida-server-16.x to /data/local/tmp and run it as root
//
// Run
//   frida -U -f com.sendo_smart -l tools/frida-dump-key.js
//   # (the spawned app resumes on its own)
//   # or attach to the already-open app:
//   frida -U com.sendo_smart -l tools/frida-dump-key.js
//
// Replace com.sendo_smart with your app's package (adb shell pm list packages).
// Output lines look like:
//   [tuya-key] name=Living Room AC  id=bfxxxxxxxxxxxxxxxxxxxx  local_key=xxxxxxxxxxxxxxxx
// Put id + local_key into ~/.config/tuya-ac/config.json (ip from your router's
// client list, or `uvx tinytuya scan`).

"use strict";

var DEVICE_BEAN_CLASSES = [
  "com.thingclips.smart.sdk.bean.DeviceBean", // newer Tuya/Thing SDK
  "com.tuya.smart.sdk.bean.DeviceBean",       // older Tuya SDK
];

function dumpKeys() {
  var found = 0;
  DEVICE_BEAN_CLASSES.forEach(function (cls) {
    try {
      Java.use(cls); // throws if the class isn't loaded in this app
    } catch (e) {
      return;
    }
    Java.choose(cls, {
      onMatch: function (inst) {
        try {
          var id = inst.getDevId ? inst.getDevId() : null;
          var key = inst.getLocalKey ? inst.getLocalKey() : null;
          var name = inst.getName ? inst.getName() : "";
          if (id && key) {
            found++;
            console.log("[tuya-key] name=" + name + "  id=" + id + "  local_key=" + key);
          }
        } catch (e) {}
      },
      onComplete: function () {},
    });
  });
  if (found === 0) {
    console.log("[tuya-key] no DeviceBean instances yet — open the device list in the app, then wait.");
  } else {
    console.log("[tuya-key] done (" + found + " device(s)).");
  }
  return found;
}

// Poll until the app has built its device list (logging in / opening the
// device list can take a while), then stop. Gives up after ~3 minutes.
if (typeof Java === "undefined" || !Java.available) {
  console.log("[tuya-key] No Java bridge here. Use Frida 16.x (17 removed the built-in " +
              "bridge) and target the Android app's process.");
} else {
  var tries = 0;
  var timer = setInterval(function () {
    tries++;
    Java.perform(function () {
      if (dumpKeys() > 0) {
        clearInterval(timer);
      } else if (tries >= 30) {
        clearInterval(timer);
        console.log("[tuya-key] Gave up after ~3 minutes. Log in, open the device list, then re-run.");
      }
    });
  }, 6000);
}

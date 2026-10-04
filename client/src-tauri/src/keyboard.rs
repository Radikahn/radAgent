// The on-screen keyboard on iOS slides up over the chat and only the composer rides up with it.
//
// Left alone, WKWebView scrolls itself to keep the focused field in view, and with the composer pinned to the bottom
// that lifts the whole app. Taking WKWebView's keyboard observers away stops it; this module watches the keyboard
// instead and tells the page how much of it the keyboard covers and how long it takes to get there (main.tsx), so the
// dock follows it. The bar WebKit puts above the keyboard (field arrows and a ✓ to close it) goes too: a tap on the
// chat closes the keyboard (main.tsx)

use std::ptr::NonNull;

use block2::RcBlock;
use objc2::ffi::class_replaceMethod;
use objc2::rc::Retained;
use objc2::runtime::{AnyClass, AnyObject, Imp, Sel};
use objc2::sel;
use objc2_foundation::{NSNotification, NSNotificationCenter, NSNumber, NSValue};
use objc2_ui_kit::{
    NSValueUIGeometryExtensions, UIKeyboardAnimationDurationUserInfoKey, UIKeyboardDidChangeFrameNotification,
    UIKeyboardDidShowNotification, UIKeyboardFrameEndUserInfoKey, UIKeyboardWillChangeFrameNotification,
    UIKeyboardWillHideNotification, UIKeyboardWillShowNotification, UIView,
};
use tauri::WebviewWindow;

pub fn install(window: &WebviewWindow) -> tauri::Result<()> {
    let page = window.clone();
    window.with_webview(move |webview| unsafe {
        let Some(view) = Retained::retain(webview.inner().cast::<UIView>()) else {
            return;
        };
        hide_accessory_bar();

        // The ones WKWebView registers in WKWebViewIOS.mm; every other observer it has stays
        let center = NSNotificationCenter::defaultCenter();
        for name in [
            UIKeyboardWillChangeFrameNotification,
            UIKeyboardDidChangeFrameNotification,
            UIKeyboardWillShowNotification,
            UIKeyboardDidShowNotification,
            UIKeyboardWillHideNotification,
        ] {
            center.removeObserver_name_object(&view, Some(name), None);
        }

        // Fires as the keyboard comes, goes, or changes height (a different keyboard, the predictive row)
        let changed = RcBlock::new(move |notification: NonNull<NSNotification>| {
            let (covered, duration) = measure(&view, notification.as_ref());
            let _ = page.eval(format!(
                "window.dispatchEvent(new CustomEvent('native-keyboard', {{ detail: {{ height: {covered}, duration: {duration} }} }}))"
            ));
        });
        // The center holds the registration for as long as the app runs
        let _ = center.addObserverForName_object_queue_usingBlock(
            Some(UIKeyboardWillChangeFrameNotification),
            None,
            None,
            &changed,
        );
    })
}

/// How many points of the webview the keyboard will cover once it settles, and how many seconds it takes to get there
unsafe fn measure(view: &UIView, notification: &NSNotification) -> (f64, f64) {
    let Some(info) = notification.userInfo() else {
        return (0.0, 0.0);
    };
    let duration = info
        .objectForKey(UIKeyboardAnimationDurationUserInfoKey)
        .and_then(|value| value.downcast::<NSNumber>().ok())
        .map_or(0.0, |number| number.doubleValue());
    let Some(frame) = info
        .objectForKey(UIKeyboardFrameEndUserInfoKey)
        .and_then(|value| value.downcast::<NSValue>().ok())
        .map(|value| value.CGRectValue())
    else {
        return (0.0, duration);
    };

    // In screen coordinates, which are the window's for an app that fills the screen
    let keyboard = view.convertRect_fromView(frame, None);
    let bounds = view.bounds();
    let bottom = bounds.origin.y + bounds.size.height;
    // An iPad keyboard floating mid-screen, or one split in two, covers nothing the dock needs to clear
    let docked = keyboard.size.width > 0.0 && keyboard.origin.y + keyboard.size.height >= bottom - 1.0;
    let covered = if docked { (bottom - keyboard.origin.y).clamp(0.0, bounds.size.height) } else { 0.0 };
    (covered.round(), duration)
}

/// The bar is whatever the focused field's view hands UIKit as its `inputAccessoryView` when it takes focus, and that
/// view is WebKit's WKContentView; replaced on that class alone, so other views keep theirs
unsafe fn hide_accessory_bar() {
    extern "C-unwind" fn none(_this: &AnyObject, _cmd: Sel) -> *mut AnyObject {
        std::ptr::null_mut()
    }
    let Some(class) = AnyClass::get(c"WKContentView") else {
        return;
    };
    let imp = std::mem::transmute::<extern "C-unwind" fn(&AnyObject, Sel) -> *mut AnyObject, Imp>(none);
    class_replaceMethod(
        (class as *const AnyClass).cast_mut(),
        sel!(inputAccessoryView),
        imp,
        c"@@:".as_ptr(),
    );
}

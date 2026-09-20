#import <Cocoa/Cocoa.h>

@interface DashboardAnalyticAppDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate>

@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) NSTextField *statusLabel;
@property(nonatomic, strong) NSButton *openBrowserButton;
@property(nonatomic, strong) NSButton *restartButton;
@property(nonatomic, strong) NSButton *stopButton;
@property(nonatomic, strong) NSTask *launcherTask;
@property(nonatomic, strong) NSURL *serverURL;
@property(nonatomic, assign) BOOL restarting;
@property(nonatomic, assign) BOOL stopping;

@end

@implementation DashboardAnalyticAppDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification;

    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    [self buildMainMenu];
    [self buildWindow];
    [self startServer];

    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (void)buildMainMenu {
    NSMenu *mainMenu = [[NSMenu alloc] initWithTitle:@""];
    NSMenuItem *applicationMenuItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:applicationMenuItem];

    NSMenu *applicationMenu = [[NSMenu alloc] initWithTitle:@"Dashboard Analytic"];
    NSMenuItem *quitItem = [[NSMenuItem alloc]
        initWithTitle:@"Stop Server and Quit Dashboard Analytic"
        action:@selector(terminate:)
        keyEquivalent:@"q"];
    [applicationMenu addItem:quitItem];
    [applicationMenuItem setSubmenu:applicationMenu];
    [NSApp setMainMenu:mainMenu];
}

- (void)buildWindow {
    NSRect frame = NSMakeRect(0, 0, 620, 210);
    NSWindowStyleMask style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable;
    self.window = [[NSWindow alloc] initWithContentRect:frame styleMask:style backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"Dashboard Analytic";
    self.window.delegate = self;
    self.window.releasedWhenClosed = NO;
    [self.window center];

    NSView *contentView = self.window.contentView;

    NSImageView *iconView = [[NSImageView alloc] initWithFrame:NSMakeRect(28, 95, 88, 88)];
    iconView.image = [NSApp applicationIconImage];
    iconView.imageScaling = NSImageScaleProportionallyUpOrDown;
    [contentView addSubview:iconView];

    NSTextField *titleLabel = [NSTextField labelWithString:@"Dashboard Analytic"];
    titleLabel.frame = NSMakeRect(136, 145, 456, 28);
    titleLabel.font = [NSFont boldSystemFontOfSize:20];
    [contentView addSubview:titleLabel];

    self.statusLabel = [NSTextField wrappingLabelWithString:@"Starting the local server…"];
    self.statusLabel.frame = NSMakeRect(136, 95, 456, 45);
    self.statusLabel.font = [NSFont systemFontOfSize:13];
    self.statusLabel.textColor = [NSColor secondaryLabelColor];
    [contentView addSubview:self.statusLabel];

    self.openBrowserButton = [NSButton buttonWithTitle:@"Open in Browser" target:self action:@selector(openInBrowser:)];
    self.openBrowserButton.frame = NSMakeRect(96, 28, 150, 36);
    self.openBrowserButton.bezelStyle = NSBezelStyleRounded;
    [contentView addSubview:self.openBrowserButton];

    self.restartButton = [NSButton buttonWithTitle:@"Restart Server" target:self action:@selector(restartServer:)];
    self.restartButton.frame = NSMakeRect(258, 28, 140, 36);
    self.restartButton.bezelStyle = NSBezelStyleRounded;
    [contentView addSubview:self.restartButton];

    self.stopButton = [NSButton buttonWithTitle:@"Stop Server and Quit" target:self action:@selector(stopServerAndQuit:)];
    self.stopButton.frame = NSMakeRect(410, 28, 182, 36);
    self.stopButton.bezelStyle = NSBezelStyleRounded;
    self.stopButton.keyEquivalent = @"\r";
    [contentView addSubview:self.stopButton];
}

- (void)startServer {
    NSString *launchScript = [[NSBundle mainBundle] pathForResource:@"launch-server" ofType:@"zsh"];
    if (launchScript == nil) {
        [self showLaunchError:@"The server launch script is missing from the application bundle."];
        return;
    }

    NSTask *task = [[NSTask alloc] init];
    task.executableURL = [NSURL fileURLWithPath:@"/bin/zsh"];
    task.arguments = @[launchScript];
    self.launcherTask = task;

    NSString *port = [NSProcessInfo processInfo].environment[@"APP_PORT"] ?: @"7278";
    self.serverURL = [NSURL URLWithString:[NSString stringWithFormat:@"http://127.0.0.1:%@", port]];

    __weak DashboardAnalyticAppDelegate *weakSelf = self;
    task.terminationHandler = ^(NSTask *finishedTask) {
        (void)finishedTask;
        dispatch_async(dispatch_get_main_queue(), ^{
            DashboardAnalyticAppDelegate *strongSelf = weakSelf;
            if (strongSelf == nil) {
                return;
            }
            strongSelf.launcherTask = nil;
            if (strongSelf.restarting && !strongSelf.stopping) {
                strongSelf.restarting = NO;
                strongSelf.statusLabel.stringValue = @"Restarting the local server…";
                [strongSelf startServer];
                return;
            }
            strongSelf.statusLabel.stringValue = strongSelf.stopping
                ? @"Server stopped."
                : @"The server has stopped.";
            [NSApp terminate:nil];
        });
    };

    NSError *error = nil;
    if (![task launchAndReturnError:&error]) {
        self.launcherTask = nil;
        [self showLaunchError:error.localizedDescription ?: @"The server process could not be started."];
        return;
    }

    self.openBrowserButton.enabled = YES;
    self.restartButton.enabled = YES;
    self.stopButton.enabled = YES;
    self.stopButton.title = @"Stop Server and Quit";
    self.statusLabel.stringValue = @"The local server is active. Keep this window open while using Dashboard Analytic.";
}

- (void)showLaunchError:(NSString *)message {
    self.statusLabel.stringValue = @"The server could not be started.";
    self.openBrowserButton.enabled = NO;
    self.restartButton.enabled = NO;
    self.stopButton.title = @"Quit";
    self.stopButton.enabled = YES;

    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Dashboard Analytic could not start";
    alert.informativeText = message;
    [alert addButtonWithTitle:@"Quit"];
    [alert beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse returnCode) {
        (void)returnCode;
        [NSApp terminate:nil];
    }];
}

- (void)openInBrowser:(id)sender {
    (void)sender;

    if (self.serverURL == nil || ![[NSWorkspace sharedWorkspace] openURL:self.serverURL]) {
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"Dashboard Analytic could not open the browser";
        alert.informativeText = @"Open the local server address manually in your browser.";
        [alert addButtonWithTitle:@"OK"];
        [alert beginSheetModalForWindow:self.window completionHandler:nil];
    }
}

- (void)restartServer:(id)sender {
    (void)sender;

    if (self.stopping || self.restarting) {
        return;
    }
    if (self.launcherTask == nil || !self.launcherTask.running) {
        [self startServer];
        return;
    }

    self.restarting = YES;
    self.statusLabel.stringValue = @"Stopping the local server before restart…";
    self.openBrowserButton.enabled = NO;
    self.restartButton.enabled = NO;
    self.stopButton.enabled = NO;
    [self.launcherTask terminate];
}

- (void)stopServerAndQuit:(id)sender {
    (void)sender;
    [NSApp terminate:nil];
}

- (BOOL)windowShouldClose:(NSWindow *)sender {
    (void)sender;
    [NSApp terminate:nil];
    return NO;
}

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    (void)sender;

    if (self.launcherTask == nil || !self.launcherTask.running) {
        return NSTerminateNow;
    }
    if (!self.stopping) {
        self.stopping = YES;
        self.restarting = NO;
        self.statusLabel.stringValue = @"Stopping the local server…";
        self.openBrowserButton.enabled = NO;
        self.restartButton.enabled = NO;
        self.stopButton.enabled = NO;
        [self.window makeKeyAndOrderFront:nil];
        [self.launcherTask terminate];
    }
    return NSTerminateCancel;
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    (void)sender;
    return YES;
}

@end

int main(int argc, const char *argv[]) {
    (void)argc;
    (void)argv;

    @autoreleasepool {
        NSApplication *application = [NSApplication sharedApplication];
        DashboardAnalyticAppDelegate *delegate = [[DashboardAnalyticAppDelegate alloc] init];
        application.delegate = delegate;
        [application run];
    }
    return EXIT_SUCCESS;
}

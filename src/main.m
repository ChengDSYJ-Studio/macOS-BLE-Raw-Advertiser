#import <Foundation/Foundation.h>
#import <CoreBluetooth/CoreBluetooth.h>
#include <ctype.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <libproc.h>
#include <signal.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

static NSString *projectRoot;
static NSString *sessionToken;
static NSDictionary *request;
static NSMutableDictionary *state;
static CBPeripheralManager *radio;
static dispatch_source_t termSource, intSource, gateTimer;
static int instanceFD = -1;
static BOOL finishing = NO;

static NSString *runtimePath(NSString *name) {
    return [[projectRoot stringByAppendingPathComponent:@".runtime"] stringByAppendingPathComponent:name];
}

static NSDictionary *readJSON(NSString *file) {
    NSData *data = [NSData dataWithContentsOfFile:file];
    id value = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : nil;
    return [value isKindOfClass:NSDictionary.class] ? value : nil;
}

static BOOL saveState(NSString *phase, NSString *message) {
    state[@"phase"] = phase;
    state[@"message"] = message;
    state[@"updatedAt"] = @(NSDate.date.timeIntervalSince1970);
    NSData *data = [NSJSONSerialization dataWithJSONObject:state options:NSJSONWritingPrettyPrinted error:NULL];
    BOOL ok = [data writeToFile:runtimePath(@"state.json") atomically:YES];
    if (ok) chmod(runtimePath(@"state.json").fileSystemRepresentation, 0600);
    fprintf(stdout, "%s: %s\n", phase.UTF8String, message.UTF8String);
    return ok;
}

static NSString *processStamp(pid_t pid) {
    struct proc_bsdinfo info = {0};
    if (proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, sizeof(info)) != sizeof(info)) return nil;
    return [NSString stringWithFormat:@"%llu.%llu", (unsigned long long)info.pbi_start_tvsec,
            (unsigned long long)info.pbi_start_tvusec];
}

static BOOL isOwnedProcess(NSDictionary *candidate) {
    pid_t pid = [candidate[@"pid"] intValue];
    if (pid < 2 || ![candidate[@"stamp"] isKindOfClass:NSString.class]) return NO;
    char executable[PROC_PIDPATHINFO_MAXSIZE] = {0};
    if (proc_pidpath(pid, executable, sizeof(executable)) <= 0) return NO;
    NSString *expected = NSBundle.mainBundle.executablePath.stringByResolvingSymlinksInPath;
    NSString *actual = [NSString stringWithUTF8String:executable].stringByResolvingSymlinksInPath;
    return [actual isEqualToString:expected] && [processStamp(pid) isEqualToString:candidate[@"stamp"]];
}

static void finish(int code, NSString *message) {
    if (finishing) return;
    finishing = YES;
    if (gateTimer) dispatch_source_cancel(gateTimer);
    [radio stopAdvertising];
    if (state) saveState(code ? @"error" : @"off", message);
    if (instanceFD >= 0) close(instanceFD);
    exit(code);
}

static NSData *decodeHex(id text) {
    if (![text isKindOfClass:NSString.class] || [text length] % 2 || [text length] > 62) return nil;
    const char *characters = [text UTF8String];
    if (!characters || strlen(characters) != [text length]) return nil;
    NSMutableData *data = NSMutableData.data;
    for (NSUInteger i = 0; i < [text length]; i += 2) {
        if (!isxdigit((unsigned char)characters[i]) || !isxdigit((unsigned char)characters[i + 1])) return nil;
        char pair[3] = {characters[i], characters[i + 1], 0};
        unsigned char byte = (unsigned char)strtoul(pair, NULL, 16);
        [data appendBytes:&byte length:1];
    }
    return data;
}

static BOOL validAD(NSData *data, BOOL scanResponse) {
    if (!data || data.length > 31) return NO;
    const unsigned char *bytes = data.bytes;
    NSUInteger offset = 0;
    BOOL flagsSeen = NO;
    while (offset < data.length) {
        NSUInteger length = bytes[offset];
        if (length == 0 || offset + 1 + length > data.length) return NO;
        unsigned char type = bytes[offset + 1];
        if (type == 1) {
            if (scanResponse || flagsSeen || length != 2) return NO;
            flagsSeen = YES;
        }
        if ((type == 0x16 && length < 3) || (type == 0x20 && length < 5) ||
            (type == 0x21 && length < 17) || (type == 0xFF && length < 3)) return NO;
        offset += 1 + length;
    }
    return YES;
}

@interface RawAdvertiser : NSObject <CBPeripheralManagerDelegate>
@property BOOL submitted;
@end

@implementation RawAdvertiser
- (void)confirmGate:(CBPeripheralManager *)manager attempt:(int)attempt {
    NSDictionary *gate = readJSON(runtimePath(@"gate-result.json"));
    if (!gate && attempt < 100) {
        // bluetoothd can deliver the callback before LLDB has published its detach result.
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 50 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
            if (!finishing) [self confirmGate:manager attempt:attempt + 1];
        });
        return;
    }
    if (!manager.isAdvertising || ![gate[@"ok"] boolValue] || ![gate[@"detached"] boolValue] ||
        ![gate[@"token"] isEqualToString:sessionToken] || [gate[@"pid"] intValue] != getpid() ||
        ![gate[@"payloadSHA256"] isEqualToString:request[@"payloadSHA256"]]) {
        finish(10, @"Session authorization or debugger detach failed. See gate.log.");
    }
    state[@"rawDataSubmitted"] = @YES;
    state[@"overAirVerified"] = @NO;
    if (!saveState(@"on", @"Raw advertising accepted. Verify the payload with an active BLE scanner.")) finish(12, @"Saving runtime status failed.");
}

- (void)peripheralManagerDidUpdateState:(CBPeripheralManager *)manager {
    if (manager.state != CBManagerStatePoweredOn) {
        if (manager.state == CBManagerStateUnauthorized) finish(6, @"Allow RawBLEAdvertiser to use Bluetooth in System Settings.");
        else if (manager.state == CBManagerStateUnsupported) finish(7, @"The system reported an unsupported Bluetooth peripheral state.");
        else if (manager.state == CBManagerStatePoweredOff) finish(8, @"Bluetooth is off. Enable it and start a new session.");
        else if (self.submitted) finish(8, @"Bluetooth state changed. This session stopped; start a new session.");
        return;
    }
    if (gateTimer) return;
    if (!saveState(@"waiting", @"Bluetooth ready; waiting for session authorization.")) finish(12, @"Saving runtime status failed.");
    gateTimer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, dispatch_get_main_queue());
    dispatch_source_set_timer(gateTimer, DISPATCH_TIME_NOW, 100 * NSEC_PER_MSEC, 10 * NSEC_PER_MSEC);
    dispatch_source_set_event_handler(gateTimer, ^{
        NSString *ready = [NSString stringWithContentsOfFile:runtimePath(@"gate.ready") encoding:NSUTF8StringEncoding error:NULL];
        if (self.submitted || ![ready isEqualToString:sessionToken]) return;
        self.submitted = YES;
        if (!saveState(@"submitting", @"Submitting the configured ADV and SCAN_RSP payloads.")) finish(12, @"Saving runtime status failed.");
        NSMutableDictionary *advertisement = [@{
            @"kCBAdvDataRawBytesDataAdvInd": decodeHex(request[@"advertisingDataHex"]),
            @"kCBMsgArgIsPrivilegedDaemon": @YES,
            @"kCBAdvDataIsConnectable": @YES
        } mutableCopy];
        NSData *scanResponse = decodeHex(request[@"scanResponseDataHex"]);
        if (scanResponse.length) advertisement[@"kCBAdvDataRawBytesDataScanRsp"] = scanResponse;
        [manager startAdvertising:advertisement];
    });
    dispatch_resume(gateTimer);
}

- (void)peripheralManagerDidStartAdvertising:(CBPeripheralManager *)manager error:(NSError *)error {
    if (error) finish(9, error.localizedDescription);
    [self confirmGate:manager attempt:0];
}
@end

int main(int argc, char **argv) { @autoreleasepool {
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc < 3) { fputs("Usage: RawBLEAdvertiser --check|--status|--stop|--run ROOT [TOKEN]\n", stderr); return 2; }
    projectRoot = [@(argv[2]) stringByStandardizingPath];
    NSString *action = @(argv[1]);
    if ([action isEqualToString:@"--check"]) {
        int (*csrCheck)(uint32_t) = dlsym(RTLD_DEFAULT, "csr_check");
        BOOL allowed = csrCheck && csrCheck(4) == 0;
        puts(allowed ? "System debugging is available." : "System debugging is restricted. Follow the setup steps in README.");
        return allowed ? 0 : 4;
    }
    if ([action isEqualToString:@"--status"] || [action isEqualToString:@"--stop"]) {
        NSDictionary *saved = readJSON(runtimePath(@"state.json"));
        if (!isOwnedProcess(saved)) {
            puts("{\"phase\":\"off\",\"message\":\"Advertising is stopped.\"}");
            return [action isEqualToString:@"--stop"] ? 0 : 1;
        }
        if ([action isEqualToString:@"--status"]) {
            NSData *data = [NSJSONSerialization dataWithJSONObject:saved options:NSJSONWritingPrettyPrinted error:NULL];
            fwrite(data.bytes, 1, data.length, stdout); puts("");
            if ([saved[@"phase"] isEqualToString:@"on"]) return 0;
            return [saved[@"phase"] isEqualToString:@"error"] ? 5 : 3;
        }
        if (kill([saved[@"pid"] intValue], SIGTERM) != 0) { perror("stop"); return 1; }
        for (int i = 0; i < 60; i++) {
            if (!isOwnedProcess(saved)) { puts("Advertising stopped."); return 0; }
            usleep(100000);
        }
        fputs("Client shutdown timed out. Check advertiser.log.\n", stderr); return 1;
    }
    if (![action isEqualToString:@"--run"] || argc != 4) return 2;
    sessionToken = @(argv[3]);
    NSString *runtime = runtimePath(@"");
    struct stat info;
    if (lstat(runtime.fileSystemRepresentation, &info) != 0 || !S_ISDIR(info.st_mode) || info.st_uid != getuid()) return 12;
    instanceFD = open(runtimePath(@"instance.lock").fileSystemRepresentation, O_CREAT | O_RDWR | O_NOFOLLOW, 0600);
    if (instanceFD < 0 || flock(instanceFD, LOCK_EX | LOCK_NB) != 0) return 3;
    int logFD = open(runtimePath(@"advertiser.log").fileSystemRepresentation, O_CREAT | O_TRUNC | O_WRONLY | O_NOFOLLOW, 0600);
    if (logFD < 0) return 12;
    dup2(logFD, STDOUT_FILENO); dup2(logFD, STDERR_FILENO); close(logFD);
    request = readJSON(runtimePath(@"request.json"));
    NSData *adv = decodeHex(request[@"advertisingDataHex"]);
    NSData *rsp = decodeHex(request[@"scanResponseDataHex"]);
    if (!adv.length || !validAD(adv, NO) || !validAD(rsp, YES) ||
        ![request[@"token"] isEqualToString:sessionToken] || ![request[@"payloadSHA256"] isKindOfClass:NSString.class]) return 2;
    NSString *stamp = processStamp(getpid());
    if (!stamp.length) return 12;
    state = [@{@"pid": @(getpid()), @"stamp": stamp, @"token": sessionToken,
               @"payloadSHA256": request[@"payloadSHA256"], @"name": request[@"name"] ?: @"Raw BLE",
               @"rawDataSubmitted": @NO, @"overAirVerified": @NO} mutableCopy];
    if (!saveState(@"starting", @"Preparing native Bluetooth.")) return 12;
    signal(SIGTERM, SIG_IGN); signal(SIGINT, SIG_IGN);
    termSource = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, SIGTERM, 0, dispatch_get_main_queue());
    intSource = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, SIGINT, 0, dispatch_get_main_queue());
    dispatch_source_set_event_handler(termSource, ^{ finish(0, @"Advertising stopped."); }); dispatch_resume(termSource);
    dispatch_source_set_event_handler(intSource, ^{ finish(0, @"Advertising stopped."); }); dispatch_resume(intSource);
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 90 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        if (![state[@"phase"] isEqualToString:@"on"]) finish(11, @"Startup timed out after 90 seconds.");
    });
    RawAdvertiser *delegate = RawAdvertiser.new;
    radio = [[CBPeripheralManager alloc] initWithDelegate:delegate queue:dispatch_get_main_queue()];
    [NSRunLoop.mainRunLoop run];
} return 0; }

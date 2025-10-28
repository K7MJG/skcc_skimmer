package main

/*
 * The MIT License (MIT)
 *
 * Copyright (c) 2015-2025 Mark J Glenn
 *
 * SKCC Skimmer - Go Edition
 * Award calculation maintains 100% parity with Xojo SKCCLogger reference
 */

import (
    "bufio"
    "context"
    "encoding/json"
    "flag"
    "fmt"
    "io"
    "math"
    "net"
    "net/http"
    "os"
    "os/signal"
    "path/filepath"
    "regexp"
    "slices"
    "sort"
    "strconv"
    "strings"
    "sync"
    "syscall"
    "time"
)

// Version information
const Version = "development"

// Global state for progress dot coordination
var (
    dotsOnLine   int
    dotsMutex    sync.Mutex
)

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

// delayedExit provides a 10-second countdown before exiting
// Allows users to see error messages when launched from shortcuts
func delayedExit(exitCode int) {
    fmt.Println() // Blank line for spacing
    done := make(chan bool, 1)

    go func() {
        for i := 10; i > 0; i-- {
            fmt.Printf("\rProgram will close in %d seconds...  ", i)
            time.Sleep(1 * time.Second)
        }
        fmt.Println()
        done <- true
    }()

    // Allow Ctrl+C to skip countdown
    sigChan := make(chan os.Signal, 1)
    signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

    select {
    case <-done:
        // Countdown finished normally
    case <-sigChan:
        // User pressed Ctrl+C
        fmt.Println("\n\nExiting...")
    }

    os.Exit(exitCode)
}

// printWithDotClear prints text, clearing any progress dots on the current line first
func printWithDotClear(text string) {
    dotsMutex.Lock()
    defer dotsMutex.Unlock()

    if dotsOnLine > 0 {
        fmt.Println() // Move to new line
    }
    fmt.Println(text)
    dotsOnLine = 0
}

// runProgressDotsTask displays progress dots at regular intervals
func runProgressDotsTask(ctx context.Context, config *Config) {
    ticker := time.NewTicker(time.Duration(config.ProgressDots.DisplaySeconds) * time.Second)
    defer ticker.Stop()
    for {
        select {
        case <-ctx.Done():
            dotsMutex.Lock()
            if dotsOnLine > 0 {
                fmt.Println()
            }
            dotsMutex.Unlock()
            return
        case <-ticker.C:
            dotsMutex.Lock()
            fmt.Print(".")
            dotsOnLine++
            if dotsOnLine >= config.ProgressDots.DotsPerLine {
                fmt.Println()
                dotsOnLine = 0
            }
            dotsMutex.Unlock()
        }
    }
}

// beep prints an ASCII bell character to produce an audible notification
func beep() {
    fmt.Print("\a")
}

// logToFile writes a line to the log file if logging is enabled
func logToFile(config *Config, line string) {
    if !config.LogFile.Enabled || config.LogFile.FileName == "" {
        return
    }

    // Open file in append mode
    file, err := os.OpenFile(config.LogFile.FileName, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
    if err != nil {
        // Silently fail - don't disrupt operation for logging errors
        return
    }
    defer file.Close()

    // Write the line with newline
    if _, err := file.WriteString(line + "\n"); err != nil {
        // Silently fail
        return
    }
}

// Network constants
const (
    RBNServer      = "telnet.reversebeacon.net"
    RBNPort        = 7000
    RBNStatusURL   = "https://reversebeacon.net/cont_includes/status.php?t=skt"
    SKCCDataURL    = "https://skccgroup.com/skimmer-data.txt"
    SKCCBaseURL    = "https://www.skccgroup.com/"
    SkedStatusURL  = "http://sked.skccgroup.com/get-status.php"
)

// US States for WAS awards
var usStates = []string{
    "AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD",
    "ME", "MI", "MN", "MO", "MS", "MT", "NC", "ND", "NE", "NH",
    "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY",
}

// All states including territories (for validation)
var allStates = []string{
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "GU", "PR", "VI",
}

// Canadian provinces
var provinces = []string{
    "AB", "BC", "MB", "NB", "NF", "NS", "ON", "PE", "QC", "SK",
}

// QRP band points
var qrpBandPoints = map[string]float64{
    "160M": 4.0, "80M": 3.0, "60M": 2.0, "40M": 2.0, "30M": 2.0,
    "20M": 1.0, "17M": 1.0, "15M": 1.0, "12M": 1.0, "10M": 3.0,
    "6M": 0.5, "2M": 0.5,
}

// SKCC calling frequencies (in kHz)
var skccCallingFrequencies = map[int][]float64{
    160: {1813.5},
    80:  {3530, 3550},
    60:  {}, // 60m has special handling (entire band)
    40:  {7038, 7055, 7114},
    30:  {10120},
    20:  {14050, 14114},
    17:  {18080},
    15:  {21050, 21114},
    12:  {24910},
    10:  {28050, 28114},
    6:   {50090},
}

// Compiled regex patterns (global for performance)
var (
    eohPattern         = regexp.MustCompile(`(?i)<eoh>`)
    eorPattern         = regexp.MustCompile(`(?i)<eor>`)
    fieldPattern       = regexp.MustCompile(`(?i)<(\w+?):\d+[^>]*>([^<\r\n]*)`)
    slashedCallPattern = regexp.MustCompile(`^([^/]+)/(.+)$|^(.+)/([^/]+)$`)
)

// ============================================================================
// DATA STRUCTURES
// ============================================================================

// Config holds all configuration settings
type Config struct {
    MyCallsign              string
    MyGridsquare            string
    SpotterRadius           int
    ADIFile                 string
    Goals                   []string
    Targets                 []string
    Bands                   []int
    Exclusions              []string
    Friends                 []string
    Verbose                 bool
    DistanceUnits           string
    K3YYear                 int
    AwardsOnly              bool
    Interactive             bool
    SpottersNearby          map[string]bool
    SpotPersistenceMinutes  int // How long to remember spots (default: 30)

    // Sub-configurations
    HighWPM      HighWPMConfig
    OffFrequency OffFrequencyConfig
    Notification NotificationConfig
    SpotWindow   SpotWindowConfig
    Sked         SkedConfig
    LogFile      LogFileConfig
    ProgressDots ProgressDotsConfig
}

// HighWPMConfig controls high WPM warnings
type HighWPMConfig struct {
    Action    string // "suppress", "warn", "always-display"
    Threshold int    // WPM threshold (default: 15)
}

// OffFrequencyConfig controls off-frequency warnings
type OffFrequencyConfig struct {
    Action    string // "suppress", "warn"
    Tolerance int    // kHz tolerance (default: 0)
}

// NotificationConfig controls notification beeps
type NotificationConfig struct {
    Enabled                   bool
    Condition                 []string // "goals", "targets", "friends"
    RenotificationDelaySeconds int
}

// SpotWindowConfig controls spot aggregation/deduplication
type SpotWindowConfig struct {
    Enabled bool
    Seconds int // Window duration to collect duplicate spots
}

// SkedConfig controls SKCC Sked monitoring
type SkedConfig struct {
    Enabled      bool
    CheckSeconds int // How often to check (default: 60)
}

// LogFileConfig controls logging to file
type LogFileConfig struct {
    Enabled          bool
    FileName         string
    DeleteOnStartup  bool
}

// ProgressDotsConfig controls progress dot display
type ProgressDotsConfig struct {
    Enabled        bool
    DisplaySeconds int
    DotsPerLine    int
}

// Rosters holds award level data for all rosters
type Rosters struct {
    Centurion map[string]int // SKCC# -> level
    Tribune   map[string]int
    Senator   map[string]int
    WAS       map[string]int // Callsign -> level
    WASC      map[string]int
    WAST      map[string]int
    WASS      map[string]int
    Prefix    map[string]int // Callsign -> level
    DXC       map[string]int // SKCC# -> level
    DXQ       map[string]int // SKCC# -> level
    QRP1x     map[string]int // SKCC# -> level
    QRP2x     map[string]int // SKCC# -> level
    TKA       map[string]int // SKCC# -> level
    RC        map[string]int // SKCC# -> level
}

// ============================================================================
// MEMBER DATA
// ============================================================================

type Member struct {
    SKCCNumber  string   // With suffix (e.g., "2748S")
    PlainNumber string   // Without suffix (e.g., "2748")
    Callsign    string   // Primary callsign (stored as-is from database, may include /SK, /EX)
    Name        string   // Member name
    SPC         string   // State/Province/Country
    OldCalls    []string // Previous callsigns
    DXCode      string   // DXCC entity code
    JoinDate    string   // Date joined SKCC
    CDate       string   // Centurion date
    TDate       string   // Tribune date
    TX8Date     string   // Tx8 date
    SDate       string   // Senator date
    Status      string   // A=Active, SK=Silent Key
}

// ============================================================================
// QSO PROCESSING & AWARD PROCESSOR
// ============================================================================

type QSO struct {
    Call       string
    SKCC       string // As logged
    SKCCPre    string // Numeric portion only
    QSODate    string
    TimeOn     string
    TimeOff    string
    Band       string
    Mode       string
    State      string
    Country    string
    DXCC       string
    TxPwr      string
    RxPwr      string
    KeyType    string
    Comment    string
    Name       string
    QTH        string
    RSTRcvd    string
    RSTSent    string
    Freq       string
    Gridsquare string
}

// ProcessedQSO represents a validated QSO with award qualification flags
type ProcessedQSO struct {
    // Basic fields
    Call        string
    CallPri     string // Member's primary call
    QSODate     string
    TimeOn      string
    TimeOff     string
    Band        string
    BandNr      int
    Mode        string
    State       string
    Country     string
    DXCC        string
    SKCCNr      string // Member number
    SKCC        string // With suffix
    TxPwr       string
    RxPwr       string
    KeyType     string
    Name        string
    QTH         string
    Comment     string
    RSTRcvd     string
    RSTSent     string
    Freq        string
    Gridsquare  string

    // Award qualification flags
    WasQSO       bool
    WasCQSO      bool
    WasTQSO      bool
    WasSQSO      bool
    TribAwardQSO bool
    SenAwardQSO  bool
    DXQQSO       bool
    DXCQSO       bool
    DXCode       string
    PfxCall      string
    Pfx          string
    PfxPts       string // SKCC number for prefix
    RagChewQSO   bool
    RagChewMins  int
    QRPx1QSO     bool
    QRPx2QSO     bool
    TKAQSO       bool
}

// AwardProcessor handles all award calculation logic
type AwardProcessor struct {
    memberDB      map[string]*Member     // SKCC number -> Member
    callsignDB    map[string][]*Member   // Callsign -> list of Members
    myMember      *Member
    myMemberNr    string
    myJoinDate    string
    myCDate       string
    myTDate       string
    myTX8Date     string
    mySDate       string
    myDXCode      string

    qsosProcessed    int
    qsosAdded        int
    qsosSkipped      []string
    qsosNeedSKCC     []NeedSKCCEntry
    qsosMissingSKCC  int
    qsosAutoMatched  []AutoMatchEntry
    processedQSOs    []ProcessedQSO
    dxcHomeUsed      bool

    // K3Y tracking: contactsForK3Y[suffix][band] = callsign
    contactsForK3Y   map[string]map[int]string
}

// NeedSKCCEntry tracks QSOs that need SKCC numbers
type NeedSKCCEntry struct {
    Date  string
    Time  string
    Entry string
}

// AutoMatchEntry tracks auto-matched QSOs
type AutoMatchEntry struct {
    QSO       QSO
    SKCCNr    string
    Member    *Member
}

// Global state
var (
    config  *Config
    members map[string]*Member // All members indexed by all callsigns (current + old)
)

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

func formatDate(dateStr string) string {
    if len(dateStr) >= 8 {
        return dateStr[0:4] + "-" + dateStr[4:6] + "-" + dateStr[6:8]
    }
    return dateStr
}

func formatTime(timeStr string) string {
    if len(timeStr) >= 4 {
        hh := timeStr[0:2]
        mm := timeStr[2:4]
        ss := "00"
        if len(timeStr) >= 6 {
            ss = timeStr[4:6]
        }
        return hh + ":" + mm + ":" + ss + "Z"
    }
    return "00:00:00Z"
}

func cleanSKCCNumber(skcc string) string {
    var result strings.Builder
    for _, r := range skcc {
        if r >= '0' && r <= '9' {
            result.WriteRune(r)
        }
    }
    return result.String()
}

func isAllDigits(s string) bool {
    if s == "" {
        return false
    }
    _, err := strconv.Atoi(s)
    return err == nil
}

// extractCallsign extracts the base callsign from a slashed call
// Examples: W1AW/4 -> W1AW, KH6/W6XX -> W6XX, VE3/K7MJG -> K7MJG
func extractCallsign(call string) string {
    call = strings.TrimSpace(strings.ToUpper(call))
    if call == "" {
        return ""
    }

    // Check for slashed callsign
    matches := slashedCallPattern.FindStringSubmatch(call)
    if matches != nil {
        // Pattern 1: prefix/call (e.g., KH6/W6XX, VE3/K7MJG)
        if matches[1] != "" && matches[2] != "" {
            prefix := matches[1]
            suffix := matches[2]
            // If prefix looks like a location indicator (short), use suffix
            if len(prefix) <= 3 || strings.Contains("KH6 KL7 KP4", prefix) {
                return suffix
            }
            // Otherwise use prefix
            return prefix
        }
        // Pattern 2: call/suffix (e.g., W1AW/4, AC2C/M)
        if matches[3] != "" && matches[4] != "" {
            return matches[3]
        }
    }

    return call
}

func normalizeDate(date string) string {
    if len(date) > 8 {
        return date[:8]
    }
    return date
}

func formatSkippedQSO(date, time, call, band, reason string) string {
    dateStr := formatDate(date)
    timeStr := formatTime(time)
    return fmt.Sprintf("Date: %s     Time: %s     Call: %-10s     Band: %-4s     Reason: %s",
        dateStr, timeStr, call, band, reason)
}

// ============================================================================
// RBN CONNECTION
// ============================================================================

type RBNConnection struct {
    callsign string
    ctx      context.Context
    cancel   context.CancelFunc
    spotChan chan string
}

// NewRBNConnection creates a new RBN connection
func NewRBNConnection(callsign string) *RBNConnection {
    ctx, cancel := context.WithCancel(context.Background())
    return &RBNConnection{
        callsign: callsign,
        ctx:      ctx,
        cancel:   cancel,
        spotChan: make(chan string, 100), // Buffered channel for spots
    }
}

// Connect establishes connection to RBN with IPv6/IPv4 fallback
func (rbn *RBNConnection) Connect() error {
    // Resolve hostname
    addrs, err := net.LookupIP(RBNServer)
    if err != nil {
        return fmt.Errorf("DNS resolution failed: %w", err)
    }

    if len(addrs) == 0 {
        return fmt.Errorf("no IP addresses found for %s", RBNServer)
    }

    // Sort addresses - prefer IPv6
    sort.Slice(addrs, func(i, j int) bool {
        return addrs[i].To4() == nil && addrs[j].To4() != nil
    })

    // Try each address
    var lastErr error
    for _, addr := range addrs {
        protocol := "IPv4"
        if addr.To4() == nil {
            protocol = "IPv6"
        }

        target := fmt.Sprintf("[%s]:%d", addr, RBNPort)
        if addr.To4() != nil {
            target = fmt.Sprintf("%s:%d", addr, RBNPort)
        }

        conn, err := net.DialTimeout("tcp", target, 30*time.Second)
        if err != nil {
            lastErr = err
            continue
        }

        // Enable TCP keepalive
        if tcpConn, ok := conn.(*net.TCPConn); ok {
            tcpConn.SetKeepAlive(true)
            tcpConn.SetKeepAlivePeriod(5 * time.Minute)
        }

        fmt.Printf("Connected to '%s' using %s.\n", RBNServer, protocol)

        // Authenticate
        if err := rbn.authenticate(conn); err != nil {
            conn.Close()
            return err
        }

        // Start reading spots in background
        go rbn.readSpots(conn)
        return nil
    }

    return fmt.Errorf("failed to connect: %w", lastErr)
}

// authenticate logs in to the RBN server
func (rbn *RBNConnection) authenticate(conn net.Conn) error {
    reader := bufio.NewReader(conn)

    // Read "call: " prompt
    conn.SetReadDeadline(time.Now().Add(10 * time.Second))
    if _, err := reader.ReadString(':'); err != nil {
        return fmt.Errorf("login prompt timeout: %w", err)
    }

    // Send callsign
    if _, err := fmt.Fprintf(conn, "%s\r\n", rbn.callsign); err != nil {
        return fmt.Errorf("failed to send callsign: %w", err)
    }

    // Wait for ">" prompt
    conn.SetReadDeadline(time.Now().Add(10 * time.Second))
    for {
        line, err := reader.ReadString('\n')
        if err != nil {
            return fmt.Errorf("authentication failed: %w", err)
        }
        if strings.Contains(line, ">") {
            break
        }
    }

    return nil
}

// readSpots reads spot data from RBN and sends to channel
func (rbn *RBNConnection) readSpots(conn net.Conn) {
    defer conn.Close()
    defer close(rbn.spotChan)

    reader := bufio.NewReader(conn)

    for {
        select {
        case <-rbn.ctx.Done():
            return
        default:
            // Set read deadline (10 minute timeout)
            conn.SetReadDeadline(time.Now().Add(10 * time.Minute))

            line, err := reader.ReadString('\n')
            if err != nil {
                if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
                    // Send keepalive
                    conn.Write([]byte("\r\n"))
                    continue
                }
                fmt.Printf("RBN connection error: %v\n", err)
                return
            }

            line = strings.TrimSpace(line)
            if line != "" {
                select {
                case rbn.spotChan <- line:
                case <-rbn.ctx.Done():
                    return
                }
            }
        }
    }
}

// Spots returns the channel for receiving spots
func (rbn *RBNConnection) Spots() <-chan string {
    return rbn.spotChan
}

// Close terminates the RBN connection
func (rbn *RBNConnection) Close() {
    rbn.cancel()
}

// ConnectAndProcessTask runs the RBN connection loop in a goroutine-safe manner
func (rbn *RBNConnection) ConnectAndProcessTask(ctx context.Context, config *Config, spotProcessor *SpotProcessor) {
    // Run RBN connection and process spots
    for {
        select {
        case <-ctx.Done():
            return
        default:
            if err := rbn.Connect(); err != nil {
                fmt.Printf("RBN connection error: %v\n", err)
                // Retry after delay
                time.Sleep(30 * time.Second)
                continue
            }

            // Connected successfully, now process spots from the channel
            for spotLine := range rbn.spotChan {
                // Verbose mode: print every RBN line
                if config.Verbose {
                    fmt.Printf("   %s\n", spotLine)
                }

                if spot := spotProcessor.ParseSpot(spotLine); spot != nil {
                    if shouldDisplay, output := spotProcessor.HandleSpot(spot); shouldDisplay {
                        printWithDotClear(output)
                        // Log to file if enabled
                        zuluDate := time.Now().UTC().Format("2006-01-02")
                        logToFile(config, zuluDate+" "+output)
                    }
                }
            }

            // Connection closed, retry after delay
            fmt.Println("RBN connection closed, reconnecting in 30 seconds...")
            time.Sleep(30 * time.Second)
        }
    }
}

// ============================================================================
// SKCC FREQUENCY UTILITIES
// ============================================================================

// isOnSKCCFrequency checks if a frequency is on an SKCC calling frequency
func isOnSKCCFrequency(frequencyKHz float64, toleranceKHz int) bool {
    tolerance := float64(toleranceKHz)

    for band, midPoints := range skccCallingFrequencies {
        // Special handling for 60m band (entire band is SKCC)
        if band == 60 {
            if frequencyKHz >= (5332-1.5) && frequencyKHz <= (5405+1.5) {
                return true
            }
        } else {
            // Check each calling frequency with tolerance
            for _, midPoint := range midPoints {
                if frequencyKHz >= (midPoint-tolerance) && frequencyKHz <= (midPoint+tolerance) {
                    return true
                }
            }
        }
    }

    return false
}

// ============================================================================
// SPOT PROCESSING
// ============================================================================

type Spot struct {
    Zulu           string
    Spotter        string
    FrequencyKHz   float64
    CallSign       string
    CallSignSuffix string
    DB             int
    WPM            int
}

// SpotProcessor handles parsing and filtering of RBN spots
type SpotProcessor struct {
    config       *Config
    members      map[string]*Member
    rosters      *Rosters
    awards             map[string]any // Contact lists from award processing
    qsosByMemberNumber map[string][]string    // QSO dates by member number (for target calculation)
    myCDate            string                 // User's Centurion award date
    myTDate      string                 // User's Tribune award date
    mySDate      string                 // User's Senator award date
    myDXCode     string                 // User's DXCC code (for DXQ foreign check)
    lastSpotted  map[string]SpotTime
    notified     map[string]float64
    pendingSpots map[string]*PendingSpot // For spot windowing/aggregation
    mu           sync.RWMutex
    zuluRegex    *regexp.Regexp
    dbRegex      *regexp.Regexp
}

// SpotTime tracks when a callsign was last spotted
type SpotTime struct {
    FrequencyKHz float64
    Timestamp    float64
}

// PendingSpot tracks a spot waiting in the aggregation window
type PendingSpot struct {
    FirstSpot     *Spot
    Output        string
    SpotterCount  int
    Timer         *time.Timer
}

// buildQSOsByMemberNumber creates an index of QSO dates by member number for target calculation
func buildQSOsByMemberNumber(qsos []ProcessedQSO) map[string][]string {
    result := make(map[string][]string)
    for _, qso := range qsos {
        memberNum := qso.SKCCNr
        if memberNum != "" {
            result[memberNum] = append(result[memberNum], qso.QSODate)
        }
    }
    return result
}

// checkCTSTarget checks if the user can help a member achieve a C, T, or S award level
// Returns the target level string (e.g., "C", "Tx5", "Sx2") or empty string if they cannot use the user
func checkCTSTarget(awardType, memberNumber, theirAwardDate string, qsosByMemberNumber map[string][]string, date1, date2 string) string {
    // Check if they can use me (all my QSOs with them are before cutoff dates)
    qsoDates, hasQSOs := qsosByMemberNumber[memberNumber]
    canUseMe := !hasQSOs
    if hasQSOs {
        canUseMe = true
        for _, qsoDate := range qsoDates {
            if qsoDate > date1 || qsoDate > date2 {
                canUseMe = false
                break
            }
        }
    }

    if !canUseMe {
        return ""
    }

    // If they don't have the award yet, they need the initial award
    if theirAwardDate == "" {
        return awardType
    }

    // Count QSOs after cutoff dates
    qsosAfterCutoff := 0
    if hasQSOs {
        for _, qsoDate := range qsoDates {
            if qsoDate > date1 && qsoDate > date2 {
                qsosAfterCutoff++
            }
        }
    }

    // Calculate target level based on QSO count
    if qsosAfterCutoff == 0 {
        return awardType
    } else if qsosAfterCutoff <= 9 {
        return fmt.Sprintf("%sx%d", awardType, qsosAfterCutoff+1)
    } else {
        level := ((qsosAfterCutoff - 10) / 5 + 3) * 5
        return fmt.Sprintf("%sx%d", awardType, level)
    }
}

// NewSpotProcessor creates a new spot processor
func NewSpotProcessor(config *Config, members map[string]*Member, rosters *Rosters, awards map[string]any, qsosByMemberNumber map[string][]string, myCDate, myTDate, mySDate, myDXCode string) *SpotProcessor {
    return &SpotProcessor{
        config:             config,
        members:            members,
        rosters:            rosters,
        awards:             awards,
        qsosByMemberNumber: qsosByMemberNumber,
        myCDate:            myCDate,
        myTDate:            myTDate,
        mySDate:            mySDate,
        myDXCode:           myDXCode,
        lastSpotted:        make(map[string]SpotTime),
        notified:           make(map[string]float64),
        pendingSpots:       make(map[string]*PendingSpot),
        zuluRegex:          regexp.MustCompile(`^([01]?[0-9]|2[0-3])[0-5][0-9]Z$`),
        dbRegex:            regexp.MustCompile(`^\s{0,1}\d{1,2} dB$`),
    }
}

// ParseSpot parses a DX spot line from RBN
// Returns nil if the line is invalid or should be filtered
func (sp *SpotProcessor) ParseSpot(line string) *Spot {
    // DX spot lines are exactly 75 characters and start with "DX de "
    if len(line) != 75 || !strings.HasPrefix(line, "DX de ") {
        return nil
    }

    // Extract components by position (RBN format is fixed-width)
    // Format: DX de SPOTTER-#:  FREQ CALL         CW  XX dB  XX WPM  BEACON  HHMMZ
    // Example: DX de N6TV-#:      14023.0  W1AW         CW  22 dB  25 WPM  K3Y     2130Z

    spotterFreq := line[6:24] // "SPOTTER-#:  FREQ"
    parts := strings.Split(spotterFreq, "-#:")
    if len(parts) != 2 {
        return nil
    }
    spotter := strings.TrimSpace(parts[0])
    freqStr := strings.TrimSpace(parts[1])

    callsign := strings.TrimSpace(line[26:35])
    cw := strings.TrimSpace(line[41:47])
    beacon := strings.TrimSpace(line[62:68])
    zulu := line[70:75]

    // Filter non-CW and beacons
    if cw != "CW" || beacon == "BEACON" {
        return nil
    }

    // Validate format
    dbField := line[47:52]
    if !sp.zuluRegex.MatchString(zulu) || !sp.dbRegex.MatchString(dbField) {
        return nil
    }

    // Extract numeric values
    dbStr := strings.TrimSpace(line[47:49])
    db, err := strconv.Atoi(dbStr)
    if err != nil {
        return nil
    }

    wpmStr := strings.TrimSpace(line[53:56])
    wpm, err := strconv.Atoi(wpmStr)
    if err != nil {
        return nil
    }

    freq, err := strconv.ParseFloat(freqStr, 64)
    if err != nil {
        return nil
    }

    // Handle callsign suffixes (e.g., W1AW/4)
    callSignSuffix := ""
    if base, suffix, found := strings.Cut(callsign, "/"); found {
        callsign = base
        callSignSuffix = strings.ToUpper(suffix)
    }

    return &Spot{
        Zulu:           zulu,
        Spotter:        spotter,
        FrequencyKHz:   freq,
        CallSign:       callsign,
        CallSignSuffix: callSignSuffix,
        DB:             db,
        WPM:            wpm,
    }
}

// HandleSpot processes a parsed spot and determines if it should be displayed
func (sp *SpotProcessor) HandleSpot(spot *Spot) (shouldDisplay bool, output string) {
    if spot == nil {
        return false, ""
    }

    // Extract and validate callsign
    callsign := extractCallsign(spot.CallSign)
    if callsign == "" {
        return false, ""
    }

    // Check exclusion list
    if slices.Contains(sp.config.Exclusions, callsign) {
        return false, ""
    }

    // Check if frequency is in configured bands
    if !sp.isInBands(spot.FrequencyKHz) {
        return false, ""
    }

    // Check if spotter is nearby
    spottedNearby := sp.config.SpottersNearby[spot.Spotter]

    // Build report components
    var report []string

    // Add spotter info if nearby or if it's the user's callsign
    if spottedNearby || callsign == sp.config.MyCallsign {
        report = append(report, fmt.Sprintf("by %s(%ddB)", spot.Spotter, spot.DB))
    }

    // Check if this is the user's callsign
    if callsign == sp.config.MyCallsign {
        report = append(report, "(you)")
    }

    // Check frequency (skip for K3Y special event)
    if callsign != "K3Y" {
        onFrequency := isOnSKCCFrequency(spot.FrequencyKHz, sp.config.OffFrequency.Tolerance)
        if !onFrequency {
            switch sp.config.OffFrequency.Action {
            case "warn":
                report = append(report, "OFF SKCC FREQUENCY!")
            case "suppress":
                return false, ""
            }
        }
    }

    // Handle WPM warnings
    switch sp.config.HighWPM.Action {
    case "always-display":
        report = append(report, fmt.Sprintf("%d WPM", spot.WPM))
    case "warn":
        if spot.WPM >= sp.config.HighWPM.Threshold {
            report = append(report, fmt.Sprintf("%d WPM!", spot.WPM))
        }
    case "suppress":
        if spot.WPM >= sp.config.HighWPM.Threshold {
            return false, ""
        }
    }

    // Check friends list
    if slices.Contains(sp.config.Friends, callsign) {
        report = append(report, "friend")
    }

    // Get goal and target hits
    k3ySuffix := ""
    if callsign == "K3Y" {
        k3ySuffix = spot.CallSignSuffix
    }
    goalList, targetList := sp.buildGoalTargetReport(callsign, spot.FrequencyKHz, k3ySuffix)

    if len(goalList) > 0 {
        report = append(report, fmt.Sprintf("YOU need them for %s", strings.Join(goalList, ",")))
    }

    if len(targetList) > 0 {
        report = append(report, fmt.Sprintf("THEY need you for %s", strings.Join(targetList, ",")))
    }

    // Determine if we should display this spot
    // Only show spots from nearby spotters for goals/targets, but always show user's callsign and friends
    isFriend := slices.Contains(sp.config.Friends, callsign)

    if !((spottedNearby && (len(goalList) > 0 || len(targetList) > 0)) ||
        callsign == sp.config.MyCallsign ||
        isFriend) {
        return false, ""
    }

    // Record spot
    sp.mu.Lock()
    sp.lastSpotted[callsign] = SpotTime{
        FrequencyKHz: spot.FrequencyKHz,
        Timestamp:    float64(time.Now().Unix()),
    }
    sp.mu.Unlock()

    // Build output string
    freqStr := fmt.Sprintf("%.1f", spot.FrequencyKHz)
    notificationFlag := sp.handleNotification(callsign, goalList, targetList)

    if callsign == "K3Y" {
        output = fmt.Sprintf("%s%sK3Y/%s on %8s %s",
            spot.Zulu, notificationFlag, spot.CallSignSuffix, freqStr, strings.Join(report, "; "))
    } else {
        // Build member info string
        memberInfo := ""
        if member, exists := sp.members[callsign]; exists {
            memberInfo = buildMemberInfo(callsign, member, sp.rosters)
        }
        output = fmt.Sprintf("%s%s%-6s %s on %8s %s",
            spot.Zulu, notificationFlag, callsign, memberInfo, freqStr, strings.Join(report, "; "))
    }

    // Handle spot windowing/aggregation if enabled
    if sp.config.SpotWindow.Enabled && sp.config.SpotWindow.Seconds > 0 {
        return sp.aggregateSpot(spot, output, goalList, targetList)
    }

    return true, output
}

// aggregateSpot handles spot windowing - collecting multiple spotters before displaying
func (sp *SpotProcessor) aggregateSpot(spot *Spot, output string, goalList, targetList []string) (bool, string) {
    callsign := extractCallsign(spot.CallSign)
    spotKey := buildSpotKey(callsign, spot.FrequencyKHz, goalList, targetList)

    sp.mu.Lock()
    defer sp.mu.Unlock()

    // Check if we already have a pending spot for this key
    if pending, exists := sp.pendingSpots[spotKey]; exists {
        // Increment spotter count
        pending.SpotterCount++
        return false, "" // Don't display yet, still aggregating
    }

    // This is the first spot for this key - create pending entry and start timer
    pending := &PendingSpot{
        FirstSpot:    spot,
        Output:       output,
        SpotterCount: 1,
    }

    // Create timer that will display the aggregated spot after window expires
    pending.Timer = time.AfterFunc(time.Duration(sp.config.SpotWindow.Seconds)*time.Second, func() {
        sp.flushPendingSpot(spotKey)
    })

    sp.pendingSpots[spotKey] = pending
    return false, "" // Don't display yet, waiting for window to expire
}

// flushPendingSpot displays an aggregated spot after the window expires
func (sp *SpotProcessor) flushPendingSpot(spotKey string) {
    sp.mu.Lock()
    pending, exists := sp.pendingSpots[spotKey]
    if !exists {
        sp.mu.Unlock()
        return
    }
    delete(sp.pendingSpots, spotKey)
    sp.mu.Unlock()

    // Modify output to show MULTIPLE(n) instead of single spotter
    output := pending.Output
    if pending.SpotterCount > 1 {
        // Replace "by CALLSIGN(SNRdB)" with "by MULTIPLE(n)"
        re := regexp.MustCompile(`by [A-Z0-9-]+\(\d+dB\)`)
        output = re.ReplaceAllString(output, fmt.Sprintf("by MULTIPLE(%d)", pending.SpotterCount))
    }

    // Display the aggregated spot
    printWithDotClear(output)

    // Log to file if enabled
    zuluDate := time.Now().UTC().Format("2006-01-02")
    logToFile(sp.config, zuluDate+" "+output)
}

// buildSpotKey creates a unique key for spot aggregation
func buildSpotKey(callsign string, freq float64, goalList, targetList []string) string {
    // Round frequency to 0.1 kHz to group nearby spots
    freqRounded := fmt.Sprintf("%.1f", freq)
    goals := strings.Join(goalList, ",")
    targets := strings.Join(targetList, ",")
    return fmt.Sprintf("%s:%s:%s:%s", callsign, freqRounded, goals, targets)
}

// handleNotification determines if a beep should be played and returns the notification flag
func (sp *SpotProcessor) handleNotification(callsign string, goalList, targetList []string) string {
    sp.mu.Lock()
    defer sp.mu.Unlock()

    now := float64(time.Now().Unix())

    // Clean expired notifications
    for call, expiry := range sp.notified {
        if now > expiry {
            delete(sp.notified, call)
        }
    }

    // Check if we should notify
    if _, exists := sp.notified[callsign]; !exists {
        if sp.shouldNotify(callsign, goalList, targetList) {
            beep()
        }

        sp.notified[callsign] = now + float64(sp.config.Notification.RenotificationDelaySeconds)
        return "+"
    }

    return " "
}

// shouldNotify determines if notification should be triggered
func (sp *SpotProcessor) shouldNotify(_ string, goalList, targetList []string) bool {
    if !sp.config.Notification.Enabled {
        return false
    }

    // Check each condition type in the notification conditions list
    hasGoals := len(goalList) > 0
    hasTargets := len(targetList) > 0

    for _, cond := range sp.config.Notification.Condition {
        switch cond {
        case "goals":
            if hasGoals {
                return true
            }
        case "targets":
            if hasTargets {
                return true
            }
        case "both":
            if hasGoals && hasTargets {
                return true
            }
        }
    }

    return false
}

// isInBands checks if a frequency is in one of the configured bands
func (sp *SpotProcessor) isInBands(freqKHz float64) bool {
    for _, band := range sp.config.Bands {
        low, high := getBandEdges(band)
        if freqKHz >= low && freqKHz <= high {
            return true
        }
    }
    return false
}

// getBandEdges returns the frequency range for a band in kHz
func getBandEdges(band int) (float64, float64) {
    switch band {
    case 160:
        return 1800.0, 2000.0
    case 80:
        return 3500.0, 4000.0
    case 60:
        return 5330.0, 5405.0
    case 40:
        return 7000.0, 7300.0
    case 30:
        return 10100.0, 10150.0
    case 20:
        return 14000.0, 14350.0
    case 17:
        return 18068.0, 18168.0
    case 15:
        return 21000.0, 21450.0
    case 12:
        return 24890.0, 24990.0
    case 10:
        return 28000.0, 29700.0
    case 6:
        return 50000.0, 54000.0
    case 2:
        return 144000.0, 148000.0
    default:
        return 0, 0
    }
}

// buildAwardGoals checks which awards a spotted member helps with (based on contacts already worked)
// Used by both RBN spot processor and Sked monitor
func buildAwardGoals(_ string, memberNumber string, state string, member *Member, awards map[string]any, myCDate, myTDate, mySDate, myDXCode string, goalList []string) []string {
    var goals []string

    // Helper to check if a goal is in the list
    contains := func(goal string) bool {
        return slices.Contains(goalList, goal)
    }

    // Process awards in specific order to match reference implementation

    // 1. BRAG (line 2488)
    if contains("BRAG") {
        goals = append(goals, "BRAG")
    }

    // 2. C (line 2495)
    // No prerequisites for C
    if contains("C") {
        // Check if we've already worked this member for Centurion
        if contactsC, ok := awards["C"].(map[string]ProcessedQSO); ok {
            if _, exists := contactsC[memberNumber]; !exists {
                goals = append(goals, formatCTSAwardLevel("C", len(contactsC), myCDate, 100))
            }
        }
    }

    // 3. T (line 2501)
    // Requires: User has C AND Member has C
    if contains("T") && effectiveDate(myCDate) != "" && effectiveDate(member.CDate) != "" {
        // Check if we've already worked this member for Tribune
        if contactsT, ok := awards["T"].(map[string]ProcessedQSO); ok {
            if _, exists := contactsT[memberNumber]; !exists {
                goals = append(goals, formatCTSAwardLevel("T", len(contactsT), myTDate, 50))
            }
        }
    }

    // 4. S (line 2507)
    // Requires: User has Tx8 (8 Tribune contacts) AND Member has T
    // Simplified: User has T award AND Member has T
    if contains("S") && effectiveDate(myTDate) != "" && effectiveDate(member.TDate) != "" {
        // Check if we've already worked this member for Senator
        if contactsS, ok := awards["S"].(map[string]ProcessedQSO); ok {
            if _, exists := contactsS[memberNumber]; !exists {
                goals = append(goals, formatCTSAwardLevel("S", len(contactsS), mySDate, 200))
            }
        }
    }

    // 5. WAS (line 2512)
    if contains("WAS") {
        // Check if we've already worked this state for WAS (US states only)
        if isUSState(state) {
            if contactsWAS, ok := awards["WAS"].(map[string]ProcessedQSO); ok {
                if _, exists := contactsWAS[state]; !exists {
                    goals = append(goals, "WAS")
                }
            }
        }
    }

    // 6. WAS-C (line 2515)
    if contains("WAS-C") {
        // Check if we've already worked this state for WAS-C (US states only, member must have Centurion)
        if isUSState(state) && effectiveDate(member.CDate) != "" {
            if contactsWASC, ok := awards["WAS-C"].(map[string]ProcessedQSO); ok {
                if _, exists := contactsWASC[state]; !exists {
                    goals = append(goals, "WAS-C")
                }
            }
        }
    }

    // 7. WAS-T (line 2518)
    if contains("WAS-T") {
        // Check if we've already worked this state for WAS-T (US states only, member must have Tribune)
        if isUSState(state) && effectiveDate(member.TDate) != "" {
            if contactsWAST, ok := awards["WAS-T"].(map[string]ProcessedQSO); ok {
                if _, exists := contactsWAST[state]; !exists {
                    goals = append(goals, "WAS-T")
                }
            }
        }
    }

    // 8. WAS-S (line 2521)
    if contains("WAS-S") {
        // Check if we've already worked this state for WAS-S (US states only, member must have Senator)
        if isUSState(state) && effectiveDate(member.SDate) != "" {
            if contactsWASS, ok := awards["WAS-S"].(map[string]ProcessedQSO); ok {
                if _, exists := contactsWASS[state]; !exists {
                    goals = append(goals, "WAS-S")
                }
            }
        }
    }

    // 9. P (line 2524)
    if contains("P") {
        // Prefix award - check if we need this prefix or a higher number
        if contactsP, ok := awards["P"].(map[string]ProcessedQSO); ok {
            // Extract prefix from call (2 or 3 character prefix)
            call := member.Callsign
            var prefix string
            if len(call) >= 3 && call[2] >= '0' && call[2] <= '9' {
                prefix = call[:3]
            } else if len(call) >= 2 {
                prefix = call[:2]
            }

            if prefix != "" {
                // Calculate total current prefix points
                totalPoints := 0
                for _, qso := range contactsP {
                    pts, _ := strconv.Atoi(qso.PfxPts)
                    totalPoints += pts
                }

                // Check if we have this prefix already
                existingQSO, exists := contactsP[prefix]
                if !exists {
                    // New prefix
                    goals = append(goals, formatPrefixAwardLevel(totalPoints, memberNumber, nil))
                } else {
                    // Check if this member number is higher
                    existingNum, _ := strconv.Atoi(existingQSO.PfxPts)
                    newNum, _ := strconv.Atoi(memberNumber)
                    if newNum > existingNum {
                        goals = append(goals, formatPrefixAwardLevel(totalPoints, memberNumber, &existingQSO))
                    }
                }
            }
        }
    }

    // 10. DX (line 2535)
    if contains("DX") {
        // DX award - check both DXC (countries) and DXQ (foreign member QSOs)
        // Single 'DX' goal encompasses both
        // Requires: dxcc_code and dxcc_code.isdigit()
        if member.DXCode != "" && isAllDigits(member.DXCode) {
            // Normalize DXCC code to 3 digits (zero-padded)
            // "1" -> "001", "291" -> "291"
            normalizedDXCode := normalizeDXCC(member.DXCode)

            // Check DXC (unique countries)
            if contactsDXC, ok := awards["DXC"].(map[string]ProcessedQSO); ok {
                if _, exists := contactsDXC[normalizedDXCode]; !exists {
                    goals = append(goals, formatDXAwardLevel("DXC", len(contactsDXC)))
                }
            }

            // Check DXQ (foreign member QSOs) - only for foreign members
            // Use normalized codes for comparison (both zero-padded to 3 digits)
            normalizedMyDXCode := normalizeDXCC(myDXCode)
            if normalizedDXCode != normalizedMyDXCode {
                if contactsDXQ, ok := awards["DXQ"].(map[string]ProcessedQSO); ok {
                    if _, exists := contactsDXQ[memberNumber]; !exists {
                        goals = append(goals, formatDXAwardLevel("DXQ", len(contactsDXQ)))
                    }
                }
            }
        }
    }

    // Also handle separate DXC/DXQ for backward compatibility
    if contains("DXC") && member.DXCode != "" && isAllDigits(member.DXCode) {
        // Normalize DXCC code to 3 digits
        normalizedDXCode := normalizeDXCC(member.DXCode)

        // DX Countries - check if we've worked this country
        if contactsDXC, ok := awards["DXC"].(map[string]ProcessedQSO); ok {
            if _, exists := contactsDXC[normalizedDXCode]; !exists {
                goals = append(goals, formatDXAwardLevel("DXC", len(contactsDXC)))
            }
        }
    }

    if contains("DXQ") && member.DXCode != "" && isAllDigits(member.DXCode) {
        // Normalize DXCC codes for comparison
        normalizedDXCode := normalizeDXCC(member.DXCode)
        normalizedMyDXCode := normalizeDXCC(myDXCode)

        // DX QSOs - check if we've already worked this foreign member
        if normalizedDXCode != normalizedMyDXCode {
            if contactsDXQ, ok := awards["DXQ"].(map[string]ProcessedQSO); ok {
                if _, exists := contactsDXQ[memberNumber]; !exists {
                    goals = append(goals, formatDXAwardLevel("DXQ", len(contactsDXQ)))
                }
            }
        }
    }

    // 11. QRP (line 2556) - Don't show for spot detection
    // Can't determine power levels from spot alone

    // 12. TKA (line 2583)
    // Only show TKA if user hasn't completed it (needs SK < 100 OR BUG < 100 OR SS < 100)
    if contains("TKA") {
        contactsTKASK, _ := awards["TKA_SK"].(map[string]ProcessedQSO)
        contactsTKABUG, _ := awards["TKA_BUG"].(map[string]ProcessedQSO)
        contactsTKASS, _ := awards["TKA_SS"].(map[string]ProcessedQSO)

        skCount := len(contactsTKASK)
        bugCount := len(contactsTKABUG)
        ssCount := len(contactsTKASS)

        // Only show TKA if requirements not yet met
        if skCount < 100 || bugCount < 100 || ssCount < 100 {
            // Check if we've already worked this member for TKA (any key type)
            _, inSK := contactsTKASK[memberNumber]
            _, inBUG := contactsTKABUG[memberNumber]
            _, inSS := contactsTKASS[memberNumber]

            if !inSK && !inBUG && !inSS {
                goals = append(goals, "TKA")
            }
        }
    }

    return goals
}

// buildAwardTargets builds list of targets (what they need you for)
func (sp *SpotProcessor) buildAwardTargets(memberNumber string, member *Member, targets []string) []string {
    var result []string

    // Only C, T, S are valid targets
    for _, target := range targets {
        switch target {
        case "C":
            // C target: check against their join date and my join date
            myMember := sp.members[sp.config.MyCallsign]
            myJoinDate := ""
            if myMember != nil {
                myJoinDate = myMember.JoinDate
            }
            targetLevel := checkCTSTarget("C", memberNumber, member.CDate,
                sp.qsosByMemberNumber, member.JoinDate, myJoinDate)
            if targetLevel != "" {
                result = append(result, targetLevel)
            }

        case "T":
            // T target: requires both have C, check against their C date and my C date
            // Check if 'T' in TARGETS and both have C award dates
            // Use simple truthiness check (non-empty string), not effectiveDate
            if member.CDate != "" && sp.myCDate != "" {
                targetLevel := checkCTSTarget("T", memberNumber, member.TDate,
                    sp.qsosByMemberNumber, member.CDate, sp.myCDate)
                if targetLevel != "" {
                    result = append(result, targetLevel)
                }
            }

        case "S":
            // S target: requires they have Tx8 and I have T, check against their Tx8 date and my T date
            // Check if 'S' in TARGETS and both have T award dates
            // Use simple truthiness check (non-empty string), not effectiveDate
            if member.TX8Date != "" && sp.myTDate != "" {
                targetLevel := checkCTSTarget("S", memberNumber, member.SDate,
                    sp.qsosByMemberNumber, member.TX8Date, sp.myTDate)
                if targetLevel != "" {
                    result = append(result, targetLevel)
                }
            }
        }
    }

    return result
}

// buildGoalTargetReport builds lists of goals and targets for a spotted callsign
func (sp *SpotProcessor) buildGoalTargetReport(callsign string, _ float64, _ string) ([]string, []string) {
    var goals []string
    var targets []string

    // Check if this is an SKCC member
    member, exists := sp.members[callsign]
    if !exists {
        return goals, targets
    }

    if callsign == sp.config.MyCallsign {
        return goals, targets
    }

    // Don't spot inactive members
    if member.Status != "A" {
        return goals, targets
    }

    // Get member's SKCC number (plain version without suffix) and state
    memberNumber := member.PlainNumber
    state := member.SPC

    // Build goals list
    goals = buildAwardGoals(callsign, memberNumber, state, member, sp.awards, sp.myCDate, sp.myTDate, sp.mySDate, sp.myDXCode, sp.config.Goals)

    // Build targets list
    targets = sp.buildAwardTargets(memberNumber, member, sp.config.Targets)

    return goals, targets
}

// ============================================================================
// SPOTTER MANAGEMENT
// ============================================================================

type Spotter struct{
    Miles int
    Bands []int
}

// SpotterManager manages RBN spotters and distance calculations
type SpotterManager struct {
    spotters map[string]Spotter
    mu       sync.RWMutex
}

// NewSpotterManager creates a new spotter manager
func NewSpotterManager() *SpotterManager {
    return &SpotterManager{
        spotters: make(map[string]Spotter),
    }
}

// LocatorToLatLong converts a Maidenhead locator to latitude/longitude
func LocatorToLatLong(locator string) (lat, lon float64, err error) {
    locator = strings.ToUpper(locator)
    length := len(locator)

    if length != 4 && length != 6 {
        return 0, 0, fmt.Errorf("invalid Maidenhead locator length: %d", length)
    }

    // Validate format
    if locator[0] < 'A' || locator[0] > 'R' ||
        locator[1] < 'A' || locator[1] > 'R' ||
        locator[2] < '0' || locator[2] > '9' ||
        locator[3] < '0' || locator[3] > '9' {
        return 0, 0, fmt.Errorf("invalid Maidenhead locator format")
    }

    if length == 6 {
        if locator[4] < 'A' || locator[4] > 'X' ||
            locator[5] < 'A' || locator[5] > 'X' {
            return 0, 0, fmt.Errorf("invalid Maidenhead locator subsquare")
        }
    }

    // Calculate base longitude and latitude
    lon = float64(locator[0]-'A')*20 - 180 + float64(locator[2]-'0')*2
    lat = float64(locator[1]-'A')*10 - 90 + float64(locator[3]-'0')

    // Add subsquare precision if 6-character
    if length == 6 {
        lon += float64(locator[4]-'A') * (2.0 / 24.0) + (1.0 / 24.0)
        lat += float64(locator[5]-'A') * (1.0 / 24.0) + (0.5 / 24.0)
    } else {
        lon += 1.0
        lat += 0.5
    }

    return lat, lon, nil
}

// CalculateDistance calculates the great-circle distance between two Maidenhead locators in km
func CalculateDistance(locator1, locator2 string) (float64, error) {
    const earthRadiusKm = 6371.0

    lat1, lon1, err := LocatorToLatLong(locator1)
    if err != nil {
        return 0, fmt.Errorf("invalid locator1: %w", err)
    }

    lat2, lon2, err := LocatorToLatLong(locator2)
    if err != nil {
        return 0, fmt.Errorf("invalid locator2: %w", err)
    }

    // Convert to radians
    lat1Rad := lat1 * math.Pi / 180.0
    lat2Rad := lat2 * math.Pi / 180.0
    dLat := (lat2 - lat1) * math.Pi / 180.0
    dLon := (lon2 - lon1) * math.Pi / 180.0

    // Haversine formula
    a := math.Sin(dLat/2)*math.Sin(dLat/2) +
        math.Cos(lat1Rad)*math.Cos(lat2Rad)*
            math.Sin(dLon/2)*math.Sin(dLon/2)

    c := 2 * math.Atan2(math.Sqrt(a), math.Sqrt(1-a))

    return earthRadiusKm * c, nil
}

// AddSpotter adds a spotter with distance and band information
func (sm *SpotterManager) AddSpotter(callsign string, myGrid, spotterGrid string, csvBands string) error {
    distKm, err := CalculateDistance(myGrid, spotterGrid)
    if err != nil {
        return err
    }

    miles := int(distKm * 0.62137) // km to miles

    // Parse bands from CSV
    validBands := map[string]bool{
        "160m": true, "80m": true, "60m": true, "40m": true, "30m": true,
        "20m": true, "17m": true, "15m": true, "12m": true, "10m": true, "6m": true,
    }

    var bands []int
    for bandStr := range strings.SplitSeq(csvBands, ",") {
        bandStr = strings.TrimSpace(bandStr)
        if validBands[bandStr] {
            // Extract numeric part (e.g., "40m" -> 40)
            bandNum, err := strconv.Atoi(strings.TrimSuffix(bandStr, "m"))
            if err == nil {
                bands = append(bands, bandNum)
            }
        }
    }

    sm.mu.Lock()
    sm.spotters[callsign] = Spotter{
        Miles: miles,
        Bands: bands,
    }
    sm.mu.Unlock()

    return nil
}

// GetDistance returns the distance to a spotter in miles
func (sm *SpotterManager) GetDistance(callsign string) (int, bool) {
    sm.mu.RLock()
    defer sm.mu.RUnlock()

    spotter, exists := sm.spotters[callsign]
    if !exists {
        return 0, false
    }

    return spotter.Miles, true
}

// SpotterDistance represents a spotter with distance
type SpotterDistance struct {
    Callsign string
    Miles    int
}

// GetNearbySpotters returns a list of spotters within the radius, sorted by distance
func (sm *SpotterManager) GetNearbySpotters(radiusMiles int) []SpotterDistance {
    sm.mu.RLock()
    defer sm.mu.RUnlock()

    var nearby []SpotterDistance
    for callsign, spotter := range sm.spotters {
        if spotter.Miles <= radiusMiles {
            nearby = append(nearby, SpotterDistance{
                Callsign: callsign,
                Miles:    spotter.Miles,
            })
        }
    }

    // Sort by distance
    sort.Slice(nearby, func(i, j int) bool {
        return nearby[i].Miles < nearby[j].Miles
    })

    return nearby
}

// DiscoverSpotters fetches RBN spotters and populates the spotter manager
func (sm *SpotterManager) DiscoverSpotters(myGrid string) error {
    client := &http.Client{
        Timeout: 10 * time.Second,
    }

    resp, err := client.Get(RBNStatusURL)
    if err != nil {
        return fmt.Errorf("failed to fetch RBN status: %w", err)
    }
    defer resp.Body.Close()

    if resp.StatusCode != 200 {
        return fmt.Errorf("RBN status returned HTTP %d", resp.StatusCode)
    }

    body, err := io.ReadAll(resp.Body)
    if err != nil {
        return fmt.Errorf("failed to read RBN status: %w", err)
    }

    html := string(body)

    // Parse HTML to extract spotter information using regex patterns
    // Match: r'<tr.*?online24h online7d total">(.*?)</tr>'
    rowRegex := regexp.MustCompile(`(?s)<tr.*?online24h online7d total">(.*?)</tr>`)
    rows := rowRegex.FindAllString(html, -1)

    // Match: r'<td.*?><a href="/dxsd1.php\?f=.*?>\s*(.*?)\s*</a>.*?</td>\s*<td.*?>\s*(.*?)</a></td>\s*<td.*?>(.*?)</td>'
    columnsRegex := regexp.MustCompile(`(?s)<td.*?><a href="/dxsd1\.php\?f=.*?>\s*(.*?)\s*</a>.*?</td>\s*<td.*?>\s*(.*?)</a></td>\s*<td.*?>(.*?)</td>`)

    for _, row := range rows {
        matches := columnsRegex.FindStringSubmatch(row)
        if len(matches) == 4 {
            callsign := strings.TrimSpace(matches[1])
            csvBands := strings.TrimSpace(matches[2])
            grid := strings.TrimSpace(matches[3])

            // Skip invalid grids
            if grid == "XX88LL" || grid == "" {
                continue
            }

            // Add spotter (errors are silently ignored for invalid grids)
            _ = sm.AddSpotter(callsign, myGrid, grid, csvBands)
        }
    }

    return nil
}

// DisplaySpotters prints the nearby spotters in a formatted list
func DisplaySpotters(sm *SpotterManager, radiusMiles int, gridSquare string, distanceUnits string) {
    nearby := sm.GetNearbySpotters(radiusMiles)

    unit := "miles"
    if distanceUnits == "km" {
        unit = "kilometers"
    }

    count := len(nearby)
    spotterWord := "spotter"
    if count != 1 {
        spotterWord = "spotters"
    }

    fmt.Printf("\nFinding RBN spotters within %d %s of '%s'...\n", radiusMiles, unit, gridSquare)
    fmt.Printf("  Found %d nearby %s:\n", count, spotterWord)

    if count == 0 {
        return
    }

    // Format spotters as "CALL(dist)"
    var formatted []string
    for _, spotter := range nearby {
        var distStr string
        if distanceUnits == "km" {
            km := int(float64(spotter.Miles) / 0.62137)
            distStr = fmt.Sprintf("%dkm", km)
        } else {
            distStr = fmt.Sprintf("%dmi", spotter.Miles)
        }
        formatted = append(formatted, fmt.Sprintf("%s(%s)", spotter.Callsign, distStr))
    }

    // Wrap to 80 characters, starting each line with "    "
    line := "    "
    for i, item := range formatted {
        if i > 0 {
            item = ", " + item
        }

        // Check if adding this item would exceed 80 chars
        if len(line)+len(item) > 80 && len(line) > 4 {
            // Print current line and start a new one
            fmt.Println(line)
            line = "    " + strings.TrimPrefix(item, ", ")
        } else {
            line += item
        }
    }

    // Print any remaining content
    if len(line) > 4 {
        fmt.Println(line)
    }
    fmt.Println()
}

// ============================================================================
// SKED MONITORING
// ============================================================================

type SkedLogin struct {
    Callsign string
    Status   string
}

// SkedMonitor manages SKCC Sked page monitoring
type SkedMonitor struct {
    config          *Config
    spotProcessor   *SpotProcessor
    members         map[string]*Member
    rosters         *Rosters
    awardProcessor  *AwardProcessor // For K3Y tracking
    previousLogins  map[string][]string
    firstPass       bool
    mu              sync.RWMutex
    k3yRegex        *regexp.Regexp
    skmRegex        *regexp.Regexp
    freqRegex       *regexp.Regexp
}

// NewSkedMonitor creates a new sked monitor
func NewSkedMonitor(config *Config, spotProcessor *SpotProcessor, members map[string]*Member, rosters *Rosters, awardProcessor *AwardProcessor) *SkedMonitor {
    return &SkedMonitor{
        config:         config,
        spotProcessor:  spotProcessor,
        members:        members,
        rosters:        rosters,
        awardProcessor: awardProcessor,
        previousLogins: make(map[string][]string),
        firstPass:      true,
        k3yRegex:       regexp.MustCompile(`\b(K3Y)/([0-9]|KP4|KH6|KL7)\b`),
        skmRegex:       regexp.MustCompile(`\b(SKM)[\/-](AF|AS|EU|NA|OC|SA)\b`),
        freqRegex:      regexp.MustCompile(`\b(\d{1,2}\.\d{3}\.\d{1,3})|(\d{1,2}\.\d{3})|(\d{4,5}\.\d{1,3})|(\d{4,5})\b\s*$`),
    }
}

// FetchLogins retrieves current logins from the SKCC Sked page
func (sm *SkedMonitor) FetchLogins() ([]SkedLogin, error) {
    client := &http.Client{
        Timeout: 10 * time.Second,
    }

    resp, err := client.Get(SkedStatusURL)
    if err != nil {
        return nil, fmt.Errorf("HTTP request failed: %w", err)
    }
    defer resp.Body.Close()

    if resp.StatusCode != 200 {
        return nil, fmt.Errorf("HTTP status %d", resp.StatusCode)
    }

    body, err := io.ReadAll(resp.Body)
    if err != nil {
        return nil, fmt.Errorf("failed to read response: %w", err)
    }

    // The SKCC Sked page returns JSON array of [callsign, status] tuples
    var rawLogins [][]string
    if err := json.Unmarshal(body, &rawLogins); err != nil {
        return nil, fmt.Errorf("JSON decode failed: %w", err)
    }

    var logins []SkedLogin
    for _, entry := range rawLogins {
        if len(entry) >= 1 {
            login := SkedLogin{
                Callsign: entry[0],
            }
            if len(entry) >= 2 {
                login.Status = entry[1]
            }
            logins = append(logins, login)
        }
    }

    return logins, nil
}

// ProcessLogins processes sked logins and returns hits for display
func (sm *SkedMonitor) ProcessLogins(logins []SkedLogin) map[string][]string {
    skedHits := make(map[string][]string)

    for _, login := range logins {
        // Skip user's own callsign
        if login.Callsign == sm.config.MyCallsign {
            continue
        }

        // Extract base callsign
        callsign := extractCallsign(login.Callsign)
        if callsign == "" {
            continue
        }

        // Check exclusion list
        if slices.Contains(sm.config.Exclusions, callsign) {
            continue
        }

        // Process this login
        report := sm.processLogin(callsign, login.Status)

        // Add to hits if there are goals, targets, or is a friend
        if len(report) > 0 {
            skedHits[callsign] = report
        }
    }

    return skedHits
}

// processLogin processes a single login and returns report items
func (sm *SkedMonitor) processLogin(callsign, status string) []string {
    var report []string

    // Add member info
    if member, exists := sm.members[callsign]; exists {
        memberInfo := sm.buildMemberInfoForSked(callsign, member)
        if memberInfo != "" {
            report = append(report, memberInfo)
        }
    }

    // Check if recently spotted
    sm.spotProcessor.mu.RLock()
    if spotTime, exists := sm.spotProcessor.lastSpotted[callsign]; exists {
        now := time.Now().Unix()
        deltaSeconds := int(now) - int(spotTime.Timestamp)

        if deltaSeconds > sm.config.SpotPersistenceMinutes*60 {
            // Spot is too old, remove it
            sm.spotProcessor.mu.RUnlock()
            sm.spotProcessor.mu.Lock()
            delete(sm.spotProcessor.lastSpotted, callsign)
            sm.spotProcessor.mu.Unlock()
            sm.spotProcessor.mu.RLock()
        } else if deltaSeconds > 60 {
            deltaMinutes := deltaSeconds / 60
            unit := "minute"
            if deltaMinutes > 1 {
                unit = "minutes"
            }
            report = append(report, fmt.Sprintf("Last spotted %d %s ago on %.1f", deltaMinutes, unit, spotTime.FrequencyKHz))
        } else {
            unit := "second"
            if deltaSeconds > 1 {
                unit = "seconds"
            }
            report = append(report, fmt.Sprintf("Last spotted %d %s ago on %.1f", deltaSeconds, unit, spotTime.FrequencyKHz))
        }
    }
    sm.spotProcessor.mu.RUnlock()

    var goalList []string
    var targetList []string

    // K3Y/SKM special event processing
    if status != "" {
        // Check for K3Y
        if matches := sm.k3yRegex.FindStringSubmatch(status); matches != nil {
            eventType := matches[1] // "K3Y"
            station := strings.ToUpper(matches[2])
            sm.processSpecialEvent(eventType, station, status, &goalList)
        } else if matches := sm.skmRegex.FindStringSubmatch(status); matches != nil {
            eventType := matches[1] // "SKM"
            region := strings.ToUpper(matches[2])
            sm.processSpecialEvent(eventType, region, status, &goalList)
        }
    }

    // Add regular goal/target matching using shared function
    if member, exists := sm.members[callsign]; exists {
        memberNumber := member.PlainNumber
        state := member.SPC
        regularGoals := buildAwardGoals(callsign, memberNumber, state, member, sm.spotProcessor.awards, sm.spotProcessor.myCDate, sm.spotProcessor.myTDate, sm.spotProcessor.mySDate, sm.spotProcessor.myDXCode, sm.config.Goals)
        goalList = append(goalList, regularGoals...)

        // Add targets using correct function (DRY - shares logic with RBN spot processing)
        regularTargets := sm.spotProcessor.buildAwardTargets(memberNumber, member, sm.config.Targets)
        targetList = append(targetList, regularTargets...)
    }

    if len(goalList) > 0 {
        report = append(report, fmt.Sprintf("YOU need them for %s", strings.Join(goalList, ",")))
    }

    if len(targetList) > 0 {
        report = append(report, fmt.Sprintf("THEY need you for %s", strings.Join(targetList, ",")))
    }

    // Check friends list
    isFriend := slices.Contains(sm.config.Friends, callsign)

    if isFriend {
        report = append(report, "friend")
    }

    if status != "" {
        // Strip HTML tags and extra whitespace
        cleanStatus := strings.TrimSpace(status)
        report = append(report, fmt.Sprintf("STATUS: %s", cleanStatus))
    }

    // Only return report if there are goals, targets, or is a friend
    if len(goalList) > 0 || len(targetList) > 0 || isFriend {
        return report
    }

    return nil
}

// buildMemberInfoForSked formats member information for Sked page display
func (sm *SkedMonitor) buildMemberInfoForSked(callsign string, member *Member) string {
    number, suffix := sm.getFullMemberNumberForSked(callsign, member)

    // Truncate name to 9 characters max
    name := member.Name
    if len(name) > 9 {
        name = name[:9]
    }

    return fmt.Sprintf("(%5s %-4s %-9s %3s)", number, suffix, name, member.SPC)
}

// getFullMemberNumberForSked returns the member number and award suffix
func (sm *SkedMonitor) getFullMemberNumberForSked(_ string, member *Member) (string, string) {
    number := member.PlainNumber
    suffix := ""
    level := 1

    // Check award dates to determine highest achievement
    sDate := effectiveDate(member.SDate)
    tDate := effectiveDate(member.TDate)
    cDate := effectiveDate(member.CDate)
    tx8Date := effectiveDate(member.TX8Date)

    // Senator is highest
    if sDate != "" {
        suffix = "S"
        if sm.rosters != nil && sm.rosters.Senator != nil {
            if lvl, exists := sm.rosters.Senator[number]; exists {
                level = lvl
            }
        }
        if level > 1 {
            suffix = fmt.Sprintf("Sx%d", level)
        }
        return number, suffix
    }

    // Tribune second
    if tDate != "" || tx8Date != "" {
        suffix = "T"
        if sm.rosters != nil && sm.rosters.Tribune != nil {
            if lvl, exists := sm.rosters.Tribune[number]; exists {
                level = lvl
            }
        }
        if level > 1 {
            suffix = fmt.Sprintf("Tx%d", level)
        }
        return number, suffix
    }

    // Centurion third
    if cDate != "" {
        suffix = "C"
        if sm.rosters != nil && sm.rosters.Centurion != nil {
            if lvl, exists := sm.rosters.Centurion[number]; exists {
                level = lvl
            }
        }
        if level > 1 {
            suffix = fmt.Sprintf("Cx%d", level)
        }
        return number, suffix
    }

    return number, suffix
}

// processSpecialEvent processes K3Y or SKM special events from status
func (sm *SkedMonitor) processSpecialEvent(eventType, station, status string, goalList *[]string) {
    // Check if K3Y is in goals
    if !slices.Contains(sm.config.Goals, "K3Y") {
        return
    }

    // Try to extract frequency from status
    if matches := sm.freqRegex.FindStringSubmatch(status); matches != nil {
        var freqKHz float64
        var freqStr string

        // Try different match groups (different frequency formats)
        for i := 1; i <= 4; i++ {
            if matches[i] != "" {
                freqStr = matches[i]
                break
            }
        }

        if freqStr != "" {
            // Parse frequency based on format
            if matches[1] != "" {
                // Format: XX.XXX.XXX (e.g., 14.050.000)
                freqStr = strings.ReplaceAll(freqStr, ".", "")
                if val, err := strconv.ParseFloat(freqStr, 64); err == nil {
                    freqKHz = val / 1000.0
                }
            } else if matches[2] != "" {
                // Format: XX.XXX (MHz, e.g., 14.050)
                if val, err := strconv.ParseFloat(freqStr, 64); err == nil {
                    freqKHz = val * 1000.0
                }
            } else if matches[3] != "" {
                // Format: XXXXX.X (kHz with decimal, e.g., 14050.0)
                freqStr = strings.ReplaceAll(freqStr, ".", "")
                if val, err := strconv.ParseFloat(freqStr, 64); err == nil {
                    freqKHz = val
                }
            } else if matches[4] != "" {
                // Format: XXXXX (kHz, e.g., 14050)
                if val, err := strconv.ParseFloat(freqStr, 64); err == nil {
                    freqKHz = val
                }
            }

            if freqKHz > 0 {
                // Determine band from frequency
                band := whichBand(freqKHz)
                if band > 0 {
                    // Check if already worked
                    alreadyWorked := false
                    if sm.awardProcessor != nil && sm.awardProcessor.contactsForK3Y != nil {
                        if bandMap, exists := sm.awardProcessor.contactsForK3Y[station]; exists {
                            if _, worked := bandMap[band]; worked {
                                alreadyWorked = true
                            }
                        }
                    }

                    // Only add to goals if not already worked
                    if !alreadyWorked {
                        if eventType == "SKM" {
                            *goalList = append(*goalList, fmt.Sprintf("SKM-%s (%dm)", station, band))
                        } else {
                            *goalList = append(*goalList, fmt.Sprintf("K3Y/%s (%dm)", station, band))
                        }
                    }
                    return
                }
            }
        }
    }

    // No frequency found or couldn't determine band, just show event without band
    if eventType == "SKM" {
        *goalList = append(*goalList, fmt.Sprintf("SKM-%s", station))
    } else {
        *goalList = append(*goalList, fmt.Sprintf("K3Y/%s", station))
    }
}

// whichBand determines the amateur band from a frequency in kHz
func whichBand(freqKHz float64) int {
    bands := []struct {
        band  int
        lower float64
        upper float64
    }{
        {160, 1800, 2000},
        {80, 3500, 4000},
        {60, 5330, 5405},
        {40, 7000, 7300},
        {30, 10100, 10150},
        {20, 14000, 14350},
        {17, 18068, 18168},
        {15, 21000, 21450},
        {12, 24890, 24990},
        {10, 28000, 29700},
        {6, 50000, 54000},
    }

    for _, b := range bands {
        if freqKHz >= b.lower && freqKHz <= b.upper {
            return b.band
        }
    }

    return 0
}

// whichARRLBand determines the amateur band from a frequency in kHz using strict ARRL band limits
// Maps frequency to ARRL band name for K3Y processing
func whichARRLBand(freqKHz float64) int {
    bands := []struct {
        band  int
        lower float64
        upper float64
    }{
        {160, 1800, 2000},
        {80, 3500, 3600},
        {40, 7000, 7125},
        {30, 10100, 10150},
        {20, 14000, 14150},
        {17, 18068, 18168},
        {15, 21000, 21450},
        {12, 24890, 24990},
        {10, 28000, 29700},
        {6, 50000, 54000},
    }

    for _, b := range bands {
        if freqKHz > b.lower && freqKHz < b.upper {
            return b.band
        }
    }

    return 0
}

// DisplayLogins fetches and displays current sked logins
func (sm *SkedMonitor) DisplayLogins() error {
    logins, err := sm.FetchLogins()
    if err != nil {
        return err
    }

    if sm.config.Verbose {
        fmt.Printf("Sked page returned %d logins\n", len(logins))
    }

    skedHits := sm.ProcessLogins(logins)

    if sm.config.Verbose {
        fmt.Printf("%d logins match goals/targets\n", len(skedHits))
    }

    if len(skedHits) > 0 {
        now := time.Now().UTC()
        zuluTime := now.Format("1504") + "Z"
        zuluDate := now.Format("2006-01-02")

        // Determine new logins
        var newLogins []string
        sm.mu.RLock()
        if !sm.firstPass {
            skedSet := make(map[string]bool)
            for call := range skedHits {
                skedSet[call] = true
            }
            prevSet := make(map[string]bool)
            for call := range sm.previousLogins {
                prevSet[call] = true
            }
            for call := range skedSet {
                if !prevSet[call] {
                    newLogins = append(newLogins, call)
                }
            }
        }
        firstPass := sm.firstPass
        sm.mu.RUnlock()

        // Display header (printWithDotClear handles newline after dots if needed)
        printWithDotClear("=========== SKCC Sked Page ===========")

        // Sort callsigns for consistent display
        var callsigns []string
        for call := range skedHits {
            callsigns = append(callsigns, call)
        }
        sort.Strings(callsigns)

        // Display each login
        for _, callsign := range callsigns {
            goalList := []string{}
            targetList := []string{}

            // Parse report to find goals and targets
            for _, item := range skedHits[callsign] {
                if goals, found := strings.CutPrefix(item, "YOU need them for "); found {
                    goalList = strings.Split(goals, ",")
                } else if targets, found := strings.CutPrefix(item, "THEY need you for "); found {
                    targetList = strings.Split(targets, ",")
                }
            }

            // Check if this is a new login
            isNew := !firstPass && slices.Contains(newLogins, callsign)

            // Handle notification
            newIndicator := " "
            if isNew {
                if shouldNotifyLogin(sm.config, goalList, targetList) {
                    beep()
                }
                newIndicator = "+"
            }

            // Format and display output
            output := fmt.Sprintf("%s%s%-6s %s", zuluTime, newIndicator, callsign, strings.Join(skedHits[callsign], "; "))
            printWithDotClear(output)

            // Log to file if enabled
            logToFile(sm.config, zuluDate+" "+output)
        }

        fmt.Println("=======================================")

        // Update previous logins
        sm.mu.Lock()
        sm.previousLogins = skedHits
        sm.firstPass = false
        sm.mu.Unlock()
    }

    return nil
}

// shouldNotifyLogin determines if notification should be triggered for a sked login
func shouldNotifyLogin(config *Config, goalList, targetList []string) bool {
    if !config.Notification.Enabled {
        return false
    }

    hasGoals := len(goalList) > 0
    hasTargets := len(targetList) > 0

    for _, cond := range config.Notification.Condition {
        switch cond {
        case "goals":
            if hasGoals {
                return true
            }
        case "targets":
            if hasTargets {
                return true
            }
        case "both":
            if hasGoals && hasTargets {
                return true
            }
        }
    }

    return false
}

// MonitorTask runs the sked monitoring loop
func (sm *SkedMonitor) MonitorTask(ctx context.Context) {
    // Do initial check immediately
    if err := sm.DisplayLogins(); err != nil {
        fmt.Printf("Problem retrieving information from the Sked Page: %v. Skipping...\n", err)
    }

    ticker := time.NewTicker(time.Duration(sm.config.Sked.CheckSeconds) * time.Second)
    defer ticker.Stop()

    for {
        select {
        case <-ctx.Done():
            return
        case <-ticker.C:
            if err := sm.DisplayLogins(); err != nil {
                fmt.Printf("Problem retrieving information from the Sked Page: %v. Skipping...\n", err)
            }
        }
    }
}

// ============================================================================
// FILE WATCHING
// ============================================================================

// FileWatcher monitors ADI file for changes and triggers award recalculation
// ============================================================================
// FILE WATCHING
// ============================================================================

type FileWatcher struct {
    config         *Config
    adiFile        string
    lastModTime    time.Time
    lastSize       int64
    mu             sync.RWMutex
    refreshFunc    func() error  // Callback to trigger award refresh
}

// NewFileWatcher creates a new file watcher
func NewFileWatcher(config *Config, adiFile string, refreshFunc func() error) *FileWatcher {
    fw := &FileWatcher{
        config:      config,
        adiFile:     adiFile,
        refreshFunc: refreshFunc,
    }

    // Initialize with current file stats to avoid false change on first check
    if stat, err := os.Stat(adiFile); err == nil {
        fw.lastModTime = stat.ModTime()
        fw.lastSize = stat.Size()
    }

    return fw
}

// WatchTask monitors the ADI file for changes
func (fw *FileWatcher) WatchTask(ctx context.Context) {
    ticker := time.NewTicker(3 * time.Second)
    defer ticker.Stop()

    for {
        select {
        case <-ctx.Done():
            return
        case <-ticker.C:
            if err := fw.checkForChanges(); err != nil {
                if !os.IsNotExist(err) {
                    fmt.Printf("Error watching log file: %v\n", err)
                }
            }
        }
    }
}

// checkForChanges checks if the ADI file has been modified
func (fw *FileWatcher) checkForChanges() error {
    stat, err := os.Stat(fw.adiFile)
    if err != nil {
        if os.IsNotExist(err) {
            // File doesn't exist yet - not an error, just skip
            return nil
        }
        return err
    }

    fw.mu.RLock()
    modTime := fw.lastModTime
    size := fw.lastSize
    fw.mu.RUnlock()

    // Check if file has been modified
    if stat.ModTime().Equal(modTime) && stat.Size() == size {
        return nil
    }

    fmt.Printf("'%s' file is changing. Waiting for write to finish...\n", fw.adiFile)

    // Wait for file size to stabilize
    if err := fw.waitForStableSize(); err != nil {
        return err
    }

    // Get final stat after file stabilized
    finalStat, err := os.Stat(fw.adiFile)
    if err != nil {
        return err
    }

    // Update tracking with final values
    fw.mu.Lock()
    fw.lastModTime = finalStat.ModTime()
    fw.lastSize = finalStat.Size()
    fw.mu.Unlock()

    // Trigger refresh
    fmt.Println("File stable, refreshing awards...")
    return fw.refresh()
}

// waitForStableSize waits until the file size stops changing
func (fw *FileWatcher) waitForStableSize() error {
    var currentSize int64

    for {
        stat, err := os.Stat(fw.adiFile)
        if err != nil {
            return err
        }

        if currentSize == stat.Size() {
            // Size hasn't changed, file is stable
            break
        }

        currentSize = stat.Size()
        time.Sleep(1 * time.Second)
    }

    return nil
}

// refresh reprocesses the ADI file and recalculates awards
func (fw *FileWatcher) refresh() error {
    if fw.refreshFunc == nil {
        fmt.Println("Warning: refresh callback not configured")
        return nil
    }

    fmt.Println("\nADI file changed - recalculating awards...")
    if err := fw.refreshFunc(); err != nil {
        fmt.Printf("Error refreshing awards: %v\n", err)
        return err
    }
    fmt.Println("Awards updated successfully")
    return nil
}

// ============================================================================
// INTERACTIVE MODE
// ============================================================================

// InteractiveMode handles user input for callsign lookups and commands
// ============================================================================
// INTERACTIVE MODE
// ============================================================================

type InteractiveMode struct {
    config         *Config
    members        map[string]*Member
    rosters        *Rosters
    awardProcessor *AwardProcessor
    awards         map[string]any
    spotProcessor  *SpotProcessor
}

// NewInteractiveMode creates a new interactive mode handler
func NewInteractiveMode(config *Config, members map[string]*Member, rosters *Rosters, ap *AwardProcessor, awards map[string]any, spotProcessor *SpotProcessor) *InteractiveMode {
    return &InteractiveMode{
        config:         config,
        members:        members,
        rosters:        rosters,
        awardProcessor: ap,
        awards:         awards,
        spotProcessor:  spotProcessor,
    }
}

// Run starts the interactive mode loop
func (im *InteractiveMode) Run() {
    fmt.Println("\nInteractive mode. Enter callsigns or \"q\" to quit, \"r\" to refresh.")

    scanner := bufio.NewScanner(os.Stdin)

    for {
        fmt.Print("> ")

        if !scanner.Scan() {
            break
        }

        input := strings.TrimSpace(scanner.Text())
        if input == "" {
            continue
        }

        command := strings.ToLower(input)

        switch command {
        case "q", "quit":
            fmt.Println("\nExiting by user request...")
            return

        case "r", "refresh":
            fmt.Println("Refreshing awards...")
            if err := im.refresh(); err != nil {
                fmt.Printf("Error refreshing: %v\n", err)
            } else {
                fmt.Println("Refresh complete!")
            }

        default:
            // Treat as callsign lookup
            im.lookupCallsigns(input)
        }
    }

    if err := scanner.Err(); err != nil {
        fmt.Printf("Error reading input: %v\n", err)
    }
}

// refresh re-reads the ADI file and recalculates awards
func (im *InteractiveMode) refresh() error {
    fmt.Println("\nRe-reading QSOs from ADI file...")

    // Re-read ADI file
    qsos, err := parseADI(im.config.ADIFile)
    if err != nil {
        return fmt.Errorf("error reading ADI file: %w", err)
    }

    // Create new award processor
    ap, err := NewAwardProcessor(im.members, im.config.MyCallsign)
    if err != nil {
        return fmt.Errorf("error creating award processor: %w", err)
    }

    // Process QSOs
    processedQSOs := ap.ProcessQSOs(qsos)

    // Save copy in ADI file order
    processedQSOsADI := make([]ProcessedQSO, len(processedQSOs))
    copy(processedQSOsADI, processedQSOs)

    // Sort chronologically for C/T/S/DX awards
    processedQSOsChrono := processedQSOs
    sort.Slice(processedQSOsChrono, func(i, j int) bool {
        if processedQSOsChrono[i].QSODate != processedQSOsChrono[j].QSODate {
            return processedQSOsChrono[i].QSODate < processedQSOsChrono[j].QSODate
        }
        return processedQSOsChrono[i].TimeOn < processedQSOsChrono[j].TimeOn
    })

    // Extract awards
    awards := ExtractAwards(processedQSOsChrono, processedQSOsADI)

    // Update stored state
    im.awardProcessor = ap
    im.awards = awards

    // Display results
    fmt.Println()
    printProgress(awards, ap)
    fmt.Println()
    printFYIMessages(awards, im.rosters, im.config, im.members)

    // Process K3Y if in goals
    if slices.Contains(im.config.Goals, "K3Y") {
        ap.processK3YQSOs(im.config.K3YYear)
        ap.printK3YContacts(im.config.K3YYear)
    }

    return nil
}

// lookupCallsigns looks up one or more callsigns (space/comma separated)
func (im *InteractiveMode) lookupCallsigns(input string) {
    // Split on spaces and commas
    items := strings.FieldsFunc(strings.ToUpper(input), func(r rune) bool {
        return r == ' ' || r == ','
    })

    for _, item := range items {
        item = strings.TrimSpace(item)
        if item == "" {
            continue
        }

        // Check if it's a member number (digits only or digits with suffix)
        if im.isNumericLookup(item) {
            im.lookupByNumber(item)
        } else {
            // Treat as callsign
            im.lookupByCallsign(item)
        }
    }

    fmt.Println()
}

// isNumericLookup checks if the input is a numeric member lookup
func (im *InteractiveMode) isNumericLookup(s string) bool {
    if len(s) == 0 {
        return false
    }
    cleaned := s
    if len(s) > 1 {
        lastChar := s[len(s)-1]
        if lastChar == 'C' || lastChar == 'T' || lastChar == 'S' {
            cleaned = s[:len(s)-1]
        }
    }
    return isAllDigits(cleaned)
}

// lookupByNumber looks up a member by SKCC number
func (im *InteractiveMode) lookupByNumber(numberStr string) {
    // Strip suffix if present
    cleaned := numberStr
    if len(numberStr) > 1 {
        lastChar := numberStr[len(numberStr)-1]
        if lastChar == 'C' || lastChar == 'T' || lastChar == 'S' {
            cleaned = numberStr[:len(numberStr)-1]
        }
    }

    // Find member with this number
    found := false
    for callsign, member := range im.members {
        if member.PlainNumber == cleaned && callsign == member.Callsign {
            im.printMemberInfo(callsign, member)
            found = true
            break
        }
    }

    if !found {
        fmt.Printf("  No member with the number %s.\n", cleaned)
    }
}

// lookupByCallsign looks up a member by callsign
func (im *InteractiveMode) lookupByCallsign(callsign string) {
    // Extract base callsign (handle slashed calls)
    extractedCall := extractCallsign(callsign)
    if extractedCall == "" {
        fmt.Printf("  %s - not an SKCC member.\n", callsign)
        return
    }

    // Look up in members database
    member, exists := im.members[extractedCall]
    if !exists {
        fmt.Printf("  %s - not an SKCC member.\n", callsign)
        return
    }

    im.printMemberInfo(extractedCall, member)
}

// printMemberInfo displays member information with goal/target analysis
func (im *InteractiveMode) printMemberInfo(callsign string, member *Member) {
    // Build member info string
    memberInfo := buildMemberInfo(callsign, member, im.rosters)

    var report []string
    report = append(report, memberInfo)

    // Check if it's the user
    myMember, exists := im.members[im.config.MyCallsign]
    if exists && member.PlainNumber == myMember.PlainNumber {
        report = append(report, "(you)")
        fmt.Printf("  %s - %s\n", callsign, strings.Join(report, "; "))
        return
    }

    // Get goal and target lists using spot processor
    memberNumber := member.PlainNumber
    state := member.SPC
    goalList := buildAwardGoals(callsign, memberNumber, state, member, im.spotProcessor.awards,
        im.spotProcessor.myCDate, im.spotProcessor.myTDate, im.spotProcessor.mySDate,
        im.spotProcessor.myDXCode, im.config.Goals)
    targetList := im.spotProcessor.buildAwardTargets(memberNumber, member, im.config.Targets)

    // Check friend status
    isFriend := slices.ContainsFunc(im.config.Friends, func(friend string) bool {
        return strings.EqualFold(friend, callsign)
    })

    if len(goalList) > 0 {
        report = append(report, fmt.Sprintf("YOU need them for %s", strings.Join(goalList, ",")))
    }

    if len(targetList) > 0 {
        report = append(report, fmt.Sprintf("THEY need you for %s", strings.Join(targetList, ",")))
    }

    if isFriend {
        report = append(report, "friend")
    }

    if len(goalList) == 0 && len(targetList) == 0 {
        report = append(report, "You don't need to work each other.")
    }

    fmt.Printf("  %s - %s\n", callsign, strings.Join(report, "; "))
}

// ============================================================================
// MEMBER INFO & GOAL/TARGET MATCHING
// ============================================================================

// buildMemberInfo formats member information for display
// Format: (NUMBER SUFFIX NAME SPC)
// Example: (12345 Cx3  John      WA)
func buildMemberInfo(callsign string, member *Member, rosters *Rosters) string {
    if member == nil {
        return ""
    }

    number, suffix := getFullMemberNumber(callsign, member, rosters)

    // Truncate name to 9 characters max
    name := member.Name
    if len(name) > 9 {
        name = name[:9]
    }

    return fmt.Sprintf("(%5s %-4s %-9s %3s)", number, suffix, name, member.SPC)
}

// getFullMemberNumber returns the member number and award suffix
// Suffix examples: "C", "Cx5", "T", "Tx3", "S", "Sx2"
func getFullMemberNumber(_ string, member *Member, rosters *Rosters) (string, string) {
    number := member.PlainNumber
    suffix := ""
    level := 1

    // Check award dates to determine highest achievement
    sDate := effectiveDate(member.SDate)
    tDate := effectiveDate(member.TDate)
    cDate := effectiveDate(member.CDate)
    tx8Date := effectiveDate(member.TX8Date)

    if sDate != "" {
        suffix = "S"
        if lvl, ok := rosters.Senator[number]; ok {
            level = lvl
        }
    } else if tDate != "" {
        suffix = "T"
        if lvl, ok := rosters.Tribune[number]; ok {
            level = lvl
        }
        // Special case: if Tx8 not achieved, cap at Tx7
        if level == 8 && tx8Date == "" {
            level = 7
        }
    } else if cDate != "" {
        suffix = "C"
        if lvl, ok := rosters.Centurion[number]; ok {
            level = lvl
        }
    }

    if level > 1 {
        suffix = fmt.Sprintf("%sx%d", suffix, level)
    }

    return number, suffix
}

// effectiveDate returns empty string if date is "0000-00-00" or empty
func effectiveDate(date string) string {
    if date == "" || date == "0000-00-00" {
        return ""
    }
    return date
}

// isUSState checks if SPC is a US state
func isUSState(spc string) bool {
    return slices.Contains(usStates, spc)
}

// ============================================================================
// CONFIGURATION
// ============================================================================

// parseTOML parses a simple TOML file without external dependencies
func parseTOML(filename string) (map[string]any, error) {
	file, err := os.Open(filename)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	config := make(map[string]any)
	var currentSection string
	scanner := bufio.NewScanner(file)

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())

		// Skip empty lines and comments
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		// Check for section header [SECTION_NAME]
		if strings.HasPrefix(line, "[") && strings.HasSuffix(line, "]") {
			currentSection = strings.Trim(line, "[]")
			config[currentSection] = make(map[string]any)
			continue
		}

		// Parse key = value
		if key, value, found := strings.Cut(line, "="); found {
			key = strings.TrimSpace(key)
			value = strings.TrimSpace(value)

			// Strip inline comments (but not inside quotes)
			if idx := strings.Index(value, "#"); idx != -1 {
				inQuotes := false
				for i, ch := range value {
					if ch == '"' {
						inQuotes = !inQuotes
					}
					if !inQuotes && i == idx {
						value = strings.TrimSpace(value[:idx])
						break
					}
				}
			}

			// Parse value type
			var parsedValue any
			if (strings.HasPrefix(value, "\"") && strings.HasSuffix(value, "\"")) ||
				(strings.HasPrefix(value, "'") && strings.HasSuffix(value, "'")) {
				// String value (double or single quotes)
				parsedValue = strings.Trim(value, "\"'")
			} else if value == "true" || value == "false" {
				// Boolean value
				parsedValue = value == "true"
			} else if intVal, err := strconv.Atoi(value); err == nil {
				// Integer value
				parsedValue = intVal
			} else {
				// Default to string if can't parse
				parsedValue = value
			}

			// Store in appropriate section
			if currentSection != "" {
				sectionMap := config[currentSection].(map[string]any)
				sectionMap[key] = parsedValue
			} else {
				config[key] = parsedValue
			}
		}
	}

	return config, scanner.Err()
}

// parseConfigTOML applies TOML config data to Config struct
func parseConfigTOML(filename string, cfg *Config) (*Config, error) {
	tomlData, err := parseTOML(filename)
	if err != nil {
		return cfg, nil // Return defaults if error
	}

	// Helper to get string from any
	getString := func(val any) string {
		if s, ok := val.(string); ok {
			return s
		}
		return ""
	}

	// Helper to get int from any
	getInt := func(val any) int {
		if i, ok := val.(int); ok {
			return i
		}
		return 0
	}

	// Helper to get bool from any
	getBool := func(val any) bool {
		if b, ok := val.(bool); ok {
			return b
		}
		return false
	}

	// Parse top-level config values
	if val, ok := tomlData["MY_CALLSIGN"]; ok {
		cfg.MyCallsign = strings.ToUpper(getString(val))
	}
	if val, ok := tomlData["MY_GRIDSQUARE"]; ok {
		cfg.MyGridsquare = strings.ToUpper(getString(val))
	}
	if val, ok := tomlData["ADI_FILE"]; ok {
		cfg.ADIFile = getString(val)
	}
	if val, ok := tomlData["GOALS"]; ok {
		validGoals := []string{"C", "T", "S", "WAS", "WAS-C", "WAS-T", "WAS-S", "P", "BRAG", "K3Y", "QRP", "DX", "TKA", "RC"}
		cfg.Goals = parseGoalsTargets(getString(val), validGoals, "goal")
	}
	if val, ok := tomlData["TARGETS"]; ok {
		validTargets := []string{"C", "T", "S"}
		cfg.Targets = parseGoalsTargets(getString(val), validTargets, "target")
	}
	if val, ok := tomlData["BANDS"]; ok {
		cfg.Bands = parseBands(getString(val))
	}
	if val, ok := tomlData["EXCLUSIONS"]; ok {
		cfg.Exclusions = strings.Fields(getString(val))
	}
	if val, ok := tomlData["FRIENDS"]; ok {
		cfg.Friends = strings.Fields(getString(val))
	}
	if val, ok := tomlData["K3Y_YEAR"]; ok {
		cfg.K3YYear = getInt(val)
	}
	if val, ok := tomlData["SPOTTER_RADIUS"]; ok {
		cfg.SpotterRadius = getInt(val)
	}
	if val, ok := tomlData["VERBOSE"]; ok {
		cfg.Verbose = getBool(val)
	}
	if val, ok := tomlData["DISTANCE_UNITS"]; ok {
		cfg.DistanceUnits = getString(val)
	}

	// Parse HIGH_WPM section
	if section, ok := tomlData["HIGH_WPM"].(map[string]any); ok {
		if val, ok := section["ACTION"]; ok {
			cfg.HighWPM.Action = getString(val)
		}
		if val, ok := section["THRESHOLD"]; ok {
			cfg.HighWPM.Threshold = getInt(val)
		}
	}

	// Parse OFF_FREQUENCY section
	if section, ok := tomlData["OFF_FREQUENCY"].(map[string]any); ok {
		if val, ok := section["ACTION"]; ok {
			cfg.OffFrequency.Action = getString(val)
		}
		if val, ok := section["TOLERANCE"]; ok {
			cfg.OffFrequency.Tolerance = getInt(val)
		}
	}

	// Parse NOTIFICATION section
	if section, ok := tomlData["NOTIFICATION"].(map[string]any); ok {
		if val, ok := section["ENABLED"]; ok {
			cfg.Notification.Enabled = getBool(val)
		}
		if val, ok := section["CONDITION"]; ok {
			condStr := getString(val)
			cfg.Notification.Condition = []string{}
			for c := range strings.SplitSeq(condStr, ",") {
				c = strings.TrimSpace(c)
				if c != "" {
					cfg.Notification.Condition = append(cfg.Notification.Condition, c)
				}
			}
		}
		if val, ok := section["RENOTIFICATION_DELAY_SECONDS"]; ok {
			cfg.Notification.RenotificationDelaySeconds = getInt(val)
		}
	}

	// Parse SKED section
	if section, ok := tomlData["SKED"].(map[string]any); ok {
		if val, ok := section["ENABLED"]; ok {
			cfg.Sked.Enabled = getBool(val)
		}
		if val, ok := section["CHECK_SECONDS"]; ok {
			cfg.Sked.CheckSeconds = getInt(val)
		}
	}

	// Parse SPOT_WINDOW section
	if section, ok := tomlData["SPOT_WINDOW"].(map[string]any); ok {
		if val, ok := section["ENABLED"]; ok {
			cfg.SpotWindow.Enabled = getBool(val)
		}
		if val, ok := section["SECONDS"]; ok {
			cfg.SpotWindow.Seconds = getInt(val)
		}
	}

	// Parse LOG_FILE section
	if section, ok := tomlData["LOG_FILE"].(map[string]any); ok {
		if val, ok := section["ENABLED"]; ok {
			cfg.LogFile.Enabled = getBool(val)
		}
		if val, ok := section["FILE_NAME"]; ok {
			cfg.LogFile.FileName = getString(val)
		}
		if val, ok := section["DELETE_ON_STARTUP"]; ok {
			cfg.LogFile.DeleteOnStartup = getBool(val)
		}
	}

	// Parse PROGRESS_DOTS section
	if section, ok := tomlData["PROGRESS_DOTS"].(map[string]any); ok {
		if val, ok := section["ENABLED"]; ok {
			cfg.ProgressDots.Enabled = getBool(val)
		}
		if val, ok := section["DISPLAY_SECONDS"]; ok {
			cfg.ProgressDots.DisplaySeconds = getInt(val)
		}
		if val, ok := section["DOTS_PER_LINE"]; ok {
			cfg.ProgressDots.DotsPerLine = getInt(val)
		}
	}

	return cfg, nil
}

func parseConfig(filename string) (*Config, error) {
    cfg := &Config{
        SpotterRadius:          750,
        Bands:                  []int{160, 80, 60, 40, 30, 20, 17, 15, 12, 10, 6},
        Verbose:                false,
        DistanceUnits:          "mi",
        K3YYear:                2026,
        SpottersNearby:         make(map[string]bool),
        SpotPersistenceMinutes: 30,
        // Initialize sub-configs with defaults
        HighWPM: HighWPMConfig{
            Action:    "always-display",
            Threshold: 15,
        },
        OffFrequency: OffFrequencyConfig{
            Action:    "suppress",
            Tolerance: 0,
        },
        Notification: NotificationConfig{
            Enabled:                   true,
            Condition:                 []string{"goals", "targets", "friends"},
            RenotificationDelaySeconds: 30,
        },
        SpotWindow: SpotWindowConfig{
            Enabled: false,
            Seconds: 10,
        },
        Sked: SkedConfig{
            Enabled:      true,
            CheckSeconds: 60,
        },
        LogFile: LogFileConfig{
            Enabled:          false,
            FileName:         "",
            DeleteOnStartup:  false,
        },
        ProgressDots: ProgressDotsConfig{
            Enabled:        true,
            DisplaySeconds: 5,
            DotsPerLine:    30,
        },
    }

    // Check if file is TOML or CFG based on extension
    if strings.HasSuffix(strings.ToLower(filename), ".toml") {
        return parseConfigTOML(filename, cfg)
    }

    file, err := os.Open(filename)
    if err != nil {
        return cfg, nil // Return defaults if no config file
    }
    defer file.Close()

    scanner := bufio.NewScanner(file)
    for scanner.Scan() {
        line := strings.TrimSpace(scanner.Text())
        if line == "" || strings.HasPrefix(line, "#") {
            continue
        }

        if key, value, found := strings.Cut(line, "="); found {
            key = strings.TrimSpace(key)
            value = strings.TrimSpace(value)

            // Helper function to strip inline comments from a line
            stripComment := func(s string) string {
                if idx := strings.Index(s, "#"); idx != -1 {
                    // Only strip if # is outside quotes
                    inQuotes := false
                    for i, ch := range s {
                        if ch == '\'' || ch == '"' {
                            inQuotes = !inQuotes
                        }
                        if !inQuotes && i == idx {
                            return strings.TrimSpace(s[:idx])
                        }
                    }
                }
                return s
            }

            // Strip inline comment from initial value
            value = stripComment(value)

            // If value starts with {, it's a multi-line dictionary - accumulate until }
            if strings.HasPrefix(value, "{") {
                for !strings.Contains(value, "}") && scanner.Scan() {
                    nextLine := stripComment(strings.TrimSpace(scanner.Text()))
                    value += " " + nextLine
                }
            }

            value = strings.Trim(value, "'\"")
            value = strings.TrimPrefix(value, "r")
            value = strings.Trim(value, "'\"")

            switch key {
            case "MY_CALLSIGN":
                cfg.MyCallsign = strings.ToUpper(value)
            case "MY_GRIDSQUARE":
                cfg.MyGridsquare = strings.ToUpper(value)
            case "ADI_FILE":
                cfg.ADIFile = value
            case "GOALS":
                validGoals := []string{"C", "T", "S", "WAS", "WAS-C", "WAS-T", "WAS-S", "P", "BRAG", "K3Y", "QRP", "DX", "TKA", "RC"}
                cfg.Goals = parseGoalsTargets(value, validGoals, "goal")
            case "TARGETS":
                validTargets := []string{"C", "T", "S"}
                cfg.Targets = parseGoalsTargets(value, validTargets, "target")
            case "BANDS":
                cfg.Bands = parseBands(value)
            case "EXCLUSIONS":
                cfg.Exclusions = strings.Fields(value)
            case "FRIENDS":
                cfg.Friends = strings.Fields(value)
            case "K3Y_YEAR":
                if v, err := strconv.Atoi(value); err == nil {
                    cfg.K3YYear = v
                }
            case "SPOTTER_RADIUS":
                if v, err := strconv.Atoi(value); err == nil {
                    cfg.SpotterRadius = v
                }
            case "VERBOSE":
                cfg.Verbose = strings.ToLower(value) == "true" || value == "1"
            case "HIGH_WPM":
                parseHighWPM(value, cfg)
            case "OFF_FREQUENCY":
                parseOffFrequency(value, cfg)
            case "NOTIFICATION":
                parseNotification(value, cfg)
            case "SPOT_WINDOW":
                parseSpotWindow(value, cfg)
            case "SKED":
                parseSked(value, cfg)
            case "LOG_FILE":
                parseLogFile(value, cfg)
            case "PROGRESS_DOTS":
                parseProgressDots(value, cfg)
            }
        }
    }

    return cfg, nil
}

// ============================================================================
// GOALS/TARGETS PARSING
// ============================================================================

func parseGoalsTargets(value string, validList []string, typeStr string) []string {
    value = strings.ToUpper(value)
    parts := strings.Split(value, ",")
    var result []string
    hasAll := false
    var exclusions []string

    // Create a map for quick validation lookup
    validMap := make(map[string]bool)
    for _, v := range validList {
        validMap[v] = true
    }

    for _, p := range parts {
        p = strings.TrimSpace(p)
        if p == "ALL" {
            hasAll = true
        } else if exclusion, found := strings.CutPrefix(p, "-"); found {
            exclusions = append(exclusions, exclusion)
        } else if p != "" && p != "NONE" {
            // Validate against allowed list
            if !validMap[p] {
                fmt.Printf("Unrecognized %s '%s'.\n", typeStr, p)
                fmt.Println("Program will close in 10 seconds...")
                time.Sleep(10 * time.Second)
                delayedExit(1)
            }
            result = append(result, p)
        }
    }

    if hasAll {
        // Use the provided valid list for ALL expansion
        for _, award := range validList {
            if !slices.Contains(exclusions, award) {
                result = append(result, award)
            }
        }
    }

    return result
}

// parseHighWPM parses HIGH_WPM dict from config
func parseHighWPM(value string, cfg *Config) {
    // Value is a dict string like "{'ACTION': 'warn', 'THRESHOLD': 35}"
    // Simple extraction - look for ACTION and THRESHOLD values
    if strings.Contains(value, "ACTION") {
        if strings.Contains(value, "'suppress'") || strings.Contains(value, "\"suppress\"") {
            cfg.HighWPM.Action = "suppress"
        } else if strings.Contains(value, "'warn'") || strings.Contains(value, "\"warn\"") {
            cfg.HighWPM.Action = "warn"
        } else if strings.Contains(value, "'always-display'") || strings.Contains(value, "\"always-display\"") {
            cfg.HighWPM.Action = "always-display"
        }
    }
    if strings.Contains(value, "THRESHOLD") {
        re := regexp.MustCompile(`THRESHOLD['"]?\s*:\s*(\d+)`)
        if matches := re.FindStringSubmatch(value); len(matches) > 1 {
            if v, err := strconv.Atoi(matches[1]); err == nil {
                cfg.HighWPM.Threshold = v
            }
        }
    }
}

// parseOffFrequency parses OFF_FREQUENCY dict from config
func parseOffFrequency(value string, cfg *Config) {
    if strings.Contains(value, "ACTION") {
        if strings.Contains(value, "'suppress'") || strings.Contains(value, "\"suppress\"") {
            cfg.OffFrequency.Action = "suppress"
        } else if strings.Contains(value, "'warn'") || strings.Contains(value, "\"warn\"") {
            cfg.OffFrequency.Action = "warn"
        }
    }
    if strings.Contains(value, "TOLERANCE") {
        re := regexp.MustCompile(`TOLERANCE['"]?\s*:\s*(\d+)`)
        if matches := re.FindStringSubmatch(value); len(matches) > 1 {
            if v, err := strconv.Atoi(matches[1]); err == nil {
                cfg.OffFrequency.Tolerance = v
            }
        }
    }
}

// parseNotification parses NOTIFICATION dict from config
func parseNotification(value string, cfg *Config) {
    if strings.Contains(value, "ENABLED") {
        cfg.Notification.Enabled = strings.Contains(value, "True") || strings.Contains(value, "true")
    }
    if strings.Contains(value, "CONDITION") {
        // Extract list: ['goals', 'targets']
        re := regexp.MustCompile(`CONDITION['"]?\s*:\s*\[([^\]]+)\]`)
        if matches := re.FindStringSubmatch(value); len(matches) > 1 {
            conditions := strings.Split(matches[1], ",")
            cfg.Notification.Condition = []string{}
            for _, c := range conditions {
                c = strings.Trim(strings.TrimSpace(c), "'\"")
                if c != "" {
                    cfg.Notification.Condition = append(cfg.Notification.Condition, c)
                }
            }
        }
    }
    if strings.Contains(value, "RENOTIFICATION_DELAY_SECONDS") {
        re := regexp.MustCompile(`RENOTIFICATION_DELAY_SECONDS['"]?\s*:\s*(\d+)`)
        if matches := re.FindStringSubmatch(value); len(matches) > 1 {
            if v, err := strconv.Atoi(matches[1]); err == nil {
                cfg.Notification.RenotificationDelaySeconds = v
            }
        }
    }
}

// parseSked parses SKED dict from config
func parseSked(value string, cfg *Config) {
    if strings.Contains(value, "ENABLED") {
        cfg.Sked.Enabled = strings.Contains(value, "True") || strings.Contains(value, "true")
    }
    if strings.Contains(value, "CHECK_SECONDS") {
        re := regexp.MustCompile(`CHECK_SECONDS['"]?\s*:\s*(\d+)`)
        if matches := re.FindStringSubmatch(value); len(matches) > 1 {
            if v, err := strconv.Atoi(matches[1]); err == nil {
                cfg.Sked.CheckSeconds = v
            }
        }
    }
}

// parseSpotWindow parses SPOT_WINDOW dict from config
func parseSpotWindow(value string, cfg *Config) {
    if strings.Contains(value, "ENABLED") {
        cfg.SpotWindow.Enabled = strings.Contains(value, "True") || strings.Contains(value, "true")
    }
    if strings.Contains(value, "SECONDS") {
        re := regexp.MustCompile(`SECONDS['"]?\s*:\s*(\d+)`)
        if matches := re.FindStringSubmatch(value); len(matches) > 1 {
            if v, err := strconv.Atoi(matches[1]); err == nil {
                cfg.SpotWindow.Seconds = v
            }
        }
    }
}

// parseLogFile parses LOG_FILE dict from config
func parseLogFile(value string, cfg *Config) {
    if strings.Contains(value, "ENABLED") {
        cfg.LogFile.Enabled = strings.Contains(value, "True") || strings.Contains(value, "true")
    }
    if strings.Contains(value, "FILE_NAME") {
        re := regexp.MustCompile(`FILE_NAME['"]?\s*:\s*['"]([^'"]+)['"]`)
        if matches := re.FindStringSubmatch(value); len(matches) > 1 {
            cfg.LogFile.FileName = matches[1]
        }
    }
    if strings.Contains(value, "DELETE_ON_STARTUP") {
        cfg.LogFile.DeleteOnStartup = strings.Contains(value, "True") || strings.Contains(value, "true")
    }
}

// parseProgressDots parses PROGRESS_DOTS dict from config
func parseProgressDots(value string, cfg *Config) {
    if strings.Contains(value, "ENABLED") {
        cfg.ProgressDots.Enabled = strings.Contains(value, "True") || strings.Contains(value, "true")
    }
    if strings.Contains(value, "DISPLAY_SECONDS") {
        re := regexp.MustCompile(`DISPLAY_SECONDS['"]?\s*:\s*(\d+)`)
        if matches := re.FindStringSubmatch(value); len(matches) > 1 {
            if v, err := strconv.Atoi(matches[1]); err == nil {
                cfg.ProgressDots.DisplaySeconds = v
            }
        }
    }
    if strings.Contains(value, "DOTS_PER_LINE") {
        re := regexp.MustCompile(`DOTS_PER_LINE['"]?\s*:\s*(\d+)`)
        if matches := re.FindStringSubmatch(value); len(matches) > 1 {
            if v, err := strconv.Atoi(matches[1]); err == nil {
                cfg.ProgressDots.DotsPerLine = v
            }
        }
    }
}

func parseBands(value string) []int {
    parts := strings.Fields(value)
    var bands []int
    for _, p := range parts {
        if b, err := strconv.Atoi(p); err == nil {
            bands = append(bands, b)
        }
    }
    return bands
}

// ============================================================================
// MEMBER DATABASE
// ============================================================================

func downloadSKCCData() error {
    fmt.Println("Downloading SKCC member data...")

    resp, err := http.Get(SKCCDataURL)
    if err != nil {
        return err
    }
    defer resp.Body.Close()

    scanner := bufio.NewScanner(resp.Body)
    members = make(map[string]*Member)

    // Skip header
    scanner.Scan()

    count := 0
    for scanner.Scan() {
        line := scanner.Text()
        parts := strings.Split(line, "|")
        if len(parts) < 12 {
            continue
        }

        member := &Member{
            SKCCNumber:  parts[0],
            PlainNumber: cleanSKCCNumber(parts[0]),
            Callsign:    strings.ToUpper(parts[1]),
            Name:        parts[2],
            SPC:         parts[3],
            DXCode:      parts[5],
            JoinDate:    normalizeADIDate(parts[6]),
            CDate:       normalizeADIDate(parts[7]),
            TDate:       normalizeADIDate(parts[8]),
            TX8Date:     normalizeADIDate(parts[9]),
            SDate:       normalizeADIDate(parts[10]),
            Status:      parts[11],
        }

        if parts[4] != "" {
            member.OldCalls = strings.Split(parts[4], ",")
        }

        // Store callsign AS-IS from database (including /SK, /EX suffixes)
        // Current callsign takes precedence - always add/overwrite
        members[member.Callsign] = member

        // Index by old callsigns - DON'T overwrite existing entries
        // Old calls don't replace current calls
        for _, oldCall := range member.OldCalls {
            if oldCall != "" {
                oldCallClean := strings.ToUpper(strings.TrimSpace(oldCall))
                // Only add if not already present (don't overwrite current calls with old calls)
                if _, exists := members[oldCallClean]; !exists {
                    members[oldCallClean] = member
                }
                // Note: Logic for inactive->active upgrades can be added if needed
            }
        }

        count++
    }

    return scanner.Err()
}

func normalizeADIDate(dateStr string) string {
	// Convert "DD Mon YYYY" to "YYYYMMDD"
	if dateStr == "" {
		return ""
	}
	t, err := time.Parse("2 Jan 2006", dateStr)
	if err != nil {
		return ""
	}
	return t.Format("20060102")
}

// ============================================================================
// ADI PARSING
// ============================================================================

func parseADI(filename string) ([]QSO, error) {
    file, err := os.Open(filename)
    if err != nil {
        return nil, err
    }
    defer file.Close()

    content, err := io.ReadAll(file)
    if err != nil {
        return nil, err
    }

    text := string(content)

    // Find end of header
    eohIdx := eohPattern.FindStringIndex(text)
    if eohIdx != nil {
        text = text[eohIdx[1]:]
    }

    // Split by <eor>
    records := eorPattern.Split(text, -1)
    var qsos []QSO

    for _, record := range records {
        if strings.TrimSpace(record) == "" {
            continue
        }

        qso := QSO{}
        isCW := false
        matches := fieldPattern.FindAllStringSubmatch(record, -1)

        for _, match := range matches {
            if len(match) >= 3 {
                field := strings.ToUpper(match[1])
                value := strings.TrimSpace(match[2])  // Trim whitespace from value

                switch field {
                case "QSO_DATE":
                    qso.QSODate = value
                case "CALL":
                    qso.Call = value
                case "STATE":
                    qso.State = strings.ToUpper(value)
                case "SKCC":
                    qso.SKCC = value
                    // Parse SKCC number - detect corruption
                    if len(value) == 0 {
                        qso.SKCCPre = ""
                    } else if isAllDigits(value) {
                        // All numeric - use as-is
                        qso.SKCCPre = value
                    } else if len(value) > 1 {
                        // Try to separate assuming only last char might be suffix
                        prefixPart := value[:len(value)-1]
                        if isAllDigits(prefixPart) {
                            // Valid format like "1923T"
                            qso.SKCCPre = prefixPart
                        } else {
                            // Corrupted format like "24S73T" - reject entirely (set to blank)
                            qso.SKCCPre = ""
                        }
                    } else {
                        qso.SKCCPre = ""
                    }
                case "TX_PWR":
                    qso.TxPwr = value
                case "RX_PWR":
                    qso.RxPwr = value
                case "DXCC":
                    qso.DXCC = value
                case "BAND":
                    qso.Band = strings.ToUpper(value)
                case "KEY_TYPE", "APP_SKCCLOGGER_KEYTYPE":
                    qso.KeyType = strings.ToUpper(value)
                case "NAME":
                    qso.Name = value
                case "TIME_ON":
                    qso.TimeOn = value
                case "TIME_OFF":
                    qso.TimeOff = value
                case "COMMENT":
                    qso.Comment = value
                case "QTH":
                    qso.QTH = value
                case "RST_RCVD":
                    qso.RSTRcvd = value
                case "RST_SENT":
                    qso.RSTSent = value
                case "FREQ":
                    qso.Freq = value
                case "GRIDSQUARE":
                    qso.Gridsquare = value
                case "MODE":
                    if strings.ToUpper(value) == "CW" {
                        isCW = true
                    }
                }
            }
        }

        if isCW {
            qsos = append(qsos, qso)
        }
    }

    return qsos, nil
}

// ============================================================================
// AWARD PROCESSOR - Core Logic
// ============================================================================

func NewAwardProcessor(memberDB map[string]*Member, myCallsign string) (*AwardProcessor, error) {
    myMember := memberDB[myCallsign]
    if myMember == nil {
        return nil, fmt.Errorf("member %s not found", myCallsign)
    }

    ap := &AwardProcessor{
        memberDB:   make(map[string]*Member),
        callsignDB: make(map[string][]*Member),
        myMember:   myMember,
    }

    // Build memberDB indexed by SKCC number AND callsignDB for GetSKCCFromCall
    // We need to iterate by member NUMBER (not by callsign) to ensure ALL members
    // who have/had a callsign are indexed properly
    seenNumbers := make(map[string]bool)

    // Helper function to add callsign to callsignDB
    addToCallsignDB := func(callsign string, member *Member) {
        callUpper := strings.ToUpper(strings.TrimSpace(callsign))
        if callUpper == "" {
            return
        }

        // Check if this member already indexed under this callsign
        found := false
        for _, m := range ap.callsignDB[callUpper] {
            if m.PlainNumber == member.PlainNumber {
                found = true
                break
            }
        }
        if !found {
            ap.callsignDB[callUpper] = append(ap.callsignDB[callUpper], member)
        }

        // Also index by base callsign if it has /SK or /EX suffix
        if baseCall, suffix, found := strings.Cut(callUpper, "/"); found {
            if suffix == "SK" || suffix == "EX" {
                found := false
                for _, m := range ap.callsignDB[baseCall] {
                    if m.PlainNumber == member.PlainNumber {
                        found = true
                        break
                    }
                }
                if !found {
                    ap.callsignDB[baseCall] = append(ap.callsignDB[baseCall], member)
                }
            }
        }
    }

    // Build list of unique members (by SKCC number)
    // This is necessary because memberDB map keys are callsigns, and multiple
    // members can share the same callsign (current for one, old for another)
    uniqueMembers := make([]*Member, 0, len(memberDB))
    for _, member := range memberDB {
        if !seenNumbers[member.PlainNumber] {
            uniqueMembers = append(uniqueMembers, member)
            ap.memberDB[member.PlainNumber] = member
            seenNumbers[member.PlainNumber] = true
        }
    }

    // Now index all callsigns for each unique member
    for _, member := range uniqueMembers {
        // Index current callsign
        addToCallsignDB(member.Callsign, member)

        // Index all old callsigns
        for _, oldCall := range member.OldCalls {
            addToCallsignDB(oldCall, member)
        }
    }

    // Set user's award dates
    ap.myMemberNr = myMember.PlainNumber
    ap.myJoinDate = myMember.JoinDate
    ap.myCDate = myMember.CDate
    ap.myTDate = myMember.TDate
    ap.myTX8Date = myMember.TX8Date
    ap.mySDate = myMember.SDate
    ap.myDXCode = myMember.DXCode

    // Initialize K3Y tracking
    ap.contactsForK3Y = make(map[string]map[int]string)

    return ap, nil
}

// GetSKCCFromCall - Direct translation of Xojo logic
func (ap *AwardProcessor) GetSKCCFromCall(logCall, logSKCC string) (string, bool) {
    // Handle SKCC="NONE" special case
    if logSKCC == "NONE" {
        return logSKCC, false
    }

    skccList := make(map[string]bool)
    var returnSKCC string
    autoMatched := false

    logCallUpper := strings.ToUpper(logCall)

    if strings.Contains(logCall, "/") {
        // Try full call with slashes first
        matchingMembers := ap.callsignDB[logCallUpper]

        if len(matchingMembers) > 0 {
            for _, mbr := range matchingMembers {
                skccList[mbr.PlainNumber] = true
            }
        } else {
            // Split and try segments
            for segment := range strings.SplitSeq(logCallUpper, "/") {
                segmentMembers := ap.callsignDB[segment]
                for _, mbr := range segmentMembers {
                    skccList[mbr.PlainNumber] = true
                }
            }
        }
    } else {
        // No slashes - straightforward lookup
        matchingMembers := ap.callsignDB[logCallUpper]
        for _, mbr := range matchingMembers {
            skccList[mbr.PlainNumber] = true
        }
    }

    // Now we have all SKCC numbers that match the callsign
    if logSKCC == "" {
        // No SKCC in log - auto-match if exactly one member
        if len(skccList) == 1 {
            for num := range skccList {
                returnSKCC = num
                autoMatched = true
                break
            }
        }
    } else {
        // SKCC in log - verify it matches
        if skccList[logSKCC] {
            returnSKCC = logSKCC
        }
    }

    return returnSKCC, autoMatched
}

// ProcessQSOs - Main processing loop for QSO validation and member matching
func (ap *AwardProcessor) ProcessQSOs(qsos []QSO) []ProcessedQSO {
    ap.processedQSOs = []ProcessedQSO{}
    ap.qsosSkipped = []string{}
    ap.qsosNeedSKCC = []NeedSKCCEntry{}
    ap.qsosAutoMatched = []AutoMatchEntry{}
    ap.qsosProcessed = 0
    ap.qsosAdded = 0
    ap.qsosMissingSKCC = 0
    ap.dxcHomeUsed = false

    // Filter QSOs: date >= user join date AND mode = CW (already done in parsing)
    for _, qso := range qsos {
        if qso.QSODate < ap.myJoinDate {
            reason := fmt.Sprintf("QSO before you joined SKCC (%s)", ap.myJoinDate)
            skipped := formatSkippedQSO(qso.QSODate, qso.TimeOn, qso.Call, qso.Band, reason)
            ap.qsosSkipped = append(ap.qsosSkipped, skipped)
            continue
        }

        logCall := qso.Call
        logSKCC := qso.SKCC
        logSKCCPre := qso.SKCCPre

        var skipReason string
        var mbrSKCCNr string
        wasAutoMatched := false

        if logSKCC == "NONE" {
            mbrSKCCNr = "NONE"
            skipReason = "SKCC field marked as NONE"
        } else {
            mbrSKCCNr, wasAutoMatched = ap.GetSKCCFromCall(logCall, logSKCCPre)

            if mbrSKCCNr == "" {
                // Determine why it failed
                logCallUpper := strings.ToUpper(logCall)
                matchingMembers := ap.callsignDB[logCallUpper]

                if len(matchingMembers) == 0 {
                    // Check slashed calls
                    if strings.Contains(logCall, "/") {
                        segments := strings.Split(logCallUpper, "/")
                        hasSegmentMatch := false
                        for _, seg := range segments {
                            if len(ap.callsignDB[seg]) > 0 {
                                hasSegmentMatch = true
                                break
                            }
                        }
                        if !hasSegmentMatch {
                            skipReason = "Not an SKCC member"
                        } else {
                            skipReason = "Multiple members have had this callsign (segments), SKCC # required"
                            ap.qsosMissingSKCC++
                            ap.qsosNeedSKCC = append(ap.qsosNeedSKCC, NeedSKCCEntry{
                                Date:  qso.QSODate,
                                Time:  qso.TimeOn,
                                Entry: fmt.Sprintf("Date: %s     Time: %s     Call: %s", formatDate(qso.QSODate), formatTime(qso.TimeOn), logCall),
                            })
                        }
                    } else {
                        skipReason = "Not an SKCC member"
                    }
                } else if len(matchingMembers) > 1 {
                    skipReason = "Multiple members have had this callsign, SKCC # required"
                    ap.qsosMissingSKCC++
                    ap.qsosNeedSKCC = append(ap.qsosNeedSKCC, NeedSKCCEntry{
                        Date:  qso.QSODate,
                        Time:  qso.TimeOn,
                        Entry: fmt.Sprintf("Date: %s     Time: %s     Call: %s", formatDate(qso.QSODate), formatTime(qso.TimeOn), logCall),
                    })
                } else {
                    skipReason = "No valid SKCC match"
                }
            }
        }

        // Skip if no valid member match
        if mbrSKCCNr == "" || mbrSKCCNr == "NONE" {
            skipped := formatSkippedQSO(qso.QSODate, qso.TimeOn, logCall, qso.Band, skipReason)
            ap.qsosSkipped = append(ap.qsosSkipped, skipped)
            continue
        }

        // Look up member
        mbr := ap.memberDB[mbrSKCCNr]
        if mbr == nil {
            reason := fmt.Sprintf("Member %s not found in database", mbrSKCCNr)
            skipped := formatSkippedQSO(qso.QSODate, qso.TimeOn, logCall, qso.Band, reason)
            ap.qsosSkipped = append(ap.qsosSkipped, skipped)
            continue
        }

        // Date validation and self-QSO check
        qsoDate := normalizeDate(qso.QSODate)
        mbrJoinDate := normalizeDate(mbr.JoinDate)

        if qsoDate >= mbrJoinDate && mbr.PlainNumber != ap.myMemberNr {
            // Valid QSO - create processed record
            processed := ap.createProcessedQSO(qso, mbr)
            ap.processedQSOs = append(ap.processedQSOs, processed)
            ap.qsosAdded++

            // Track auto-matched
            if wasAutoMatched {
                ap.qsosAutoMatched = append(ap.qsosAutoMatched, AutoMatchEntry{
                    QSO:    qso,
                    SKCCNr: mbrSKCCNr,
                    Member: mbr,
                })
            }
        } else {
            // Invalid - determine reason
            if mbr.PlainNumber == ap.myMemberNr {
                skipReason = "Self QSO"
            } else if qsoDate < mbrJoinDate {
                skipReason = fmt.Sprintf("QSO before member joined (%s)", mbrJoinDate)
            } else {
                skipReason = "Invalid QSO date"
            }
            skipped := formatSkippedQSO(qso.QSODate, qso.TimeOn, logCall, qso.Band, skipReason)
            ap.qsosSkipped = append(ap.qsosSkipped, skipped)
        }

        ap.qsosProcessed++
    }

    return ap.processedQSOs
}

// createProcessedQSO creates a ProcessedQSO with all award qualifications
func (ap *AwardProcessor) createProcessedQSO(qso QSO, mbr *Member) ProcessedQSO {
    // Extract band number
    bandNr := 0
    if strings.HasSuffix(strings.ToUpper(qso.Band), "M") {
        bandStr := qso.Band[:len(qso.Band)-1]
        bandNr, _ = strconv.Atoi(bandStr)
    }

    // Determine state
    state := qso.State
    if state == "" {
        state = mbr.SPC
    }
    state = strings.ToUpper(state)

    // DC -> MD for WAS
    if state == "DC" {
        state = "MD"
    }

    // Determine DXCC
    dxcc := qso.DXCC
    if dxcc == "" || dxcc == "000" {
        dxcc = mbr.DXCode
    }
    // Normalize to 3 digits
    if len(dxcc) > 0 && len(dxcc) < 3 {
        for len(dxcc) < 3 {
            dxcc = "0" + dxcc
        }
    }

    // Use member name if log name empty
    name := qso.Name
    if name == "" {
        name = mbr.Name
    }

    processed := ProcessedQSO{
        Call:       qso.Call,
        CallPri:    mbr.Callsign,
        QSODate:    qso.QSODate,
        TimeOn:     qso.TimeOn,
        TimeOff:    qso.TimeOff,
        Band:       qso.Band,
        BandNr:     bandNr,
        Mode:       qso.Mode,
        State:      state,
        DXCC:       dxcc,
        SKCCNr:     mbr.PlainNumber,
        SKCC:       mbr.SKCCNumber,
        TxPwr:      qso.TxPwr,
        RxPwr:      qso.RxPwr,
        KeyType:    qso.KeyType,
        Name:       name,
        QTH:        qso.QTH,
        Comment:    qso.Comment,
        RSTRcvd:    qso.RSTRcvd,
        RSTSent:    qso.RSTSent,
        Freq:       qso.Freq,
        Gridsquare: qso.Gridsquare,
    }

    // Set country
    if slices.Contains(allStates, state) {
        processed.Country = "USA"
    } else if slices.Contains(provinces, state) {
        processed.Country = "Canada"
    }

    // Apply award qualifications
    ap.applyAwardQualifications(&processed, qso, mbr)

    return processed
}

// applyAwardQualifications sets all award-specific flags
func (ap *AwardProcessor) applyAwardQualifications(processed *ProcessedQSO, qso QSO, mbr *Member) {
    qsoDate := normalizeDate(qso.QSODate)

    // WAS Awards
    if slices.Contains(usStates, processed.State) {
        processed.WasQSO = true

        // WAS-C (started 2011-06-12)
        if mbr.CDate != "" && qsoDate >= "20110612" {
            mbrCDate := normalizeDate(mbr.CDate)
            if qsoDate >= mbrCDate {
                processed.WasCQSO = true
            }
        }

        // WAS-T (started 2016-02-01)
        if mbr.TDate != "" && qsoDate >= "20160201" {
            mbrTDate := normalizeDate(mbr.TDate)
            if qsoDate >= mbrTDate {
                processed.WasTQSO = true
            }
        }

        // WAS-S (started 2016-02-01)
        if mbr.SDate != "" && qsoDate >= "20160201" {
            mbrSDate := normalizeDate(mbr.SDate)
            if qsoDate >= mbrSDate {
                processed.WasSQSO = true
            }
        }
    }

    // Tribune Award (both Centurion, started 2007-03-01)
    myCDate := normalizeDate(ap.myCDate)
    mbrCDate := normalizeDate(mbr.CDate)
    if myCDate != "" && mbrCDate != "" &&
        qsoDate >= myCDate && qsoDate >= mbrCDate && qsoDate >= "20070301" {
        processed.TribAwardQSO = true
    }

    // Senator Award (I have Tx8, they have Tribune, started 2013-08-01)
    myTX8Date := normalizeDate(ap.myTX8Date)
    mbrTDate := normalizeDate(mbr.TDate)
    if qsoDate >= "20130801" && myTX8Date != "" && mbrTDate != "" &&
        qsoDate >= myTX8Date && qsoDate >= mbrTDate {
        processed.SenAwardQSO = true
    }

    // DX Awards
    if processed.DXCC != "" && processed.DXCC != "000" {
        // DXC - unique countries (allow one home country QSO)
        if processed.DXCC != ap.myDXCode {
            processed.DXCQSO = true
            processed.DXCode = processed.DXCC
        } else if !ap.dxcHomeUsed {
            processed.DXCQSO = true
            processed.DXCode = processed.DXCC
            ap.dxcHomeUsed = true
        }

        // DXQ - foreign member QSOs
        if processed.DXCC != ap.myDXCode {
            processed.DXQQSO = true
        }
    }

    // Prefix Award - started on 20130101
    // Split by /, try each segment, use the one that has valid SKCC
    if qsoDate >= "20130101" {
        for pfxCall := range strings.SplitSeq(processed.Call, "/") {
            // Check if this segment has a valid SKCC member
            pfxSKCCNr, _ := ap.GetSKCCFromCall(pfxCall, mbr.PlainNumber)
            if pfxSKCCNr != "" {
                processed.PfxCall = pfxCall
                // Extract prefix from the segment that matched
                if len(pfxCall) >= 3 && pfxCall[2] >= '0' && pfxCall[2] <= '9' {
                    processed.Pfx = pfxCall[:3]
                } else if len(pfxCall) >= 2 {
                    processed.Pfx = pfxCall[:2]
                }
                processed.PfxPts = pfxSKCCNr
                break  // Use first matching segment
            }
        }
    }

    // QRP Awards
    if qso.TxPwr != "" {
        txPwr, _ := strconv.ParseFloat(qso.TxPwr, 64)
        if txPwr > 0 && txPwr <= 5.0 {
            processed.QRPx1QSO = true

            if qso.RxPwr != "" {
                rxPwr, _ := strconv.ParseFloat(qso.RxPwr, 64)
                if rxPwr > 0 && rxPwr <= 5.0 {
                    processed.QRPx2QSO = true
                }
            }
        }
    }

    // Rag Chew Award (30+ minutes)
    if qso.TimeOn != "" && qso.TimeOff != "" {
        duration := calculateDuration(qso.TimeOn, qso.TimeOff)
        if duration >= 30 {
            processed.RagChewQSO = true
            processed.RagChewMins = duration
        }
    }

    // TKA (Triple Key Award started 10-Nov-2018)
    if qso.QSODate >= "20181110" && qso.KeyType != "" {
        kt := strings.ToUpper(qso.KeyType)
        if kt == "SK" || kt == "S" || kt == "BUG" || kt == "B" || kt == "SS" {
            processed.TKAQSO = true
        }
    }
}

func calculateDuration(timeOn, timeOff string) int {
	parseToTime := func(t string) (time.Time, error) {
		var layout string
		if len(t) >= 6 {
			layout = "150405"
			t = t[:6]
		} else if len(t) >= 4 {
			layout = "1504"
			t = t[:4]
		} else {
			return time.Time{}, fmt.Errorf("invalid time format")
		}
		return time.Parse(layout, t)
	}

	t1, err := parseToTime(timeOn)
	if err != nil {
		return 0
	}
	t2, err := parseToTime(timeOff)
	if err != nil {
		return 0
	}

	duration := t2.Sub(t1)
	if duration < 0 {
		duration += 24 * time.Hour
	}

	return int(duration.Minutes())
}

// ============================================================================
// AWARD EXTRACTION
// ============================================================================

// ExtractAwards extracts award-specific contacts from processed QSOs
// Uses dual-pass processing: chrono for C/T/S/DX, adiOrder for WAS/P/QRP/TKA/BRAG/RC
func ExtractAwards(chrono []ProcessedQSO, adiOrder []ProcessedQSO) map[string]any {
    awards := make(map[string]any)

    // C, T, S awards - use chronological order (oldest QSO first)
    contactsC := make(map[string]ProcessedQSO)
    contactsT := make(map[string]ProcessedQSO)
    contactsS := make(map[string]ProcessedQSO)

    for _, qso := range chrono {
        key := qso.SKCCNr

        // Centurion - all members
        if _, exists := contactsC[key]; !exists {
            contactsC[key] = qso
        }

        // Tribune - both Centurion
        if qso.TribAwardQSO {
            if _, exists := contactsT[key]; !exists {
                contactsT[key] = qso
            }
        }

        // Senator - I have Tx8, they have T/S
        if qso.SenAwardQSO {
            if _, exists := contactsS[key]; !exists {
                contactsS[key] = qso
            }
        }
    }

    awards["C"] = contactsC
    awards["T"] = contactsT
    awards["S"] = contactsS

    // WAS variants - use ADI file order
    contactsWAS := make(map[string]ProcessedQSO)
    contactsWASC := make(map[string]ProcessedQSO)
    contactsWAST := make(map[string]ProcessedQSO)
    contactsWASS := make(map[string]ProcessedQSO)

    for _, qso := range adiOrder {
        if qso.WasQSO {
            if _, exists := contactsWAS[qso.State]; !exists {
                contactsWAS[qso.State] = qso
            }
        }
        if qso.WasCQSO {
            if _, exists := contactsWASC[qso.State]; !exists {
                contactsWASC[qso.State] = qso
            }
        }
        if qso.WasTQSO {
            if _, exists := contactsWAST[qso.State]; !exists {
                contactsWAST[qso.State] = qso
            }
        }
        if qso.WasSQSO {
            if _, exists := contactsWASS[qso.State]; !exists {
                contactsWASS[qso.State] = qso
            }
        }
    }

    awards["WAS"] = contactsWAS
    awards["WAS-C"] = contactsWASC
    awards["WAS-T"] = contactsWAST
    awards["WAS-S"] = contactsWASS

    // Prefix - ONE entry per prefix (NOT per prefix+band combination)
    // Keep QSO with HIGHEST member number for each prefix - use ADI file order
    contactsP := make(map[string]ProcessedQSO)
    for _, qso := range adiOrder {
        if qso.Pfx != "" && qso.PfxPts != "" {
            existing, exists := contactsP[qso.Pfx]
            if !exists {
                contactsP[qso.Pfx] = qso
            } else {
                // Compare member numbers - keep higher
                existingNum, _ := strconv.Atoi(existing.PfxPts)
                newNum, _ := strconv.Atoi(qso.PfxPts)
                if newNum > existingNum {
                    contactsP[qso.Pfx] = qso
                }
            }
        }
    }
    awards["P"] = contactsP

    // QRP - Keep first QSO per member/band, but upgrade to QRP 2x if found - use ADI file order
    // Keep first QSO, upgrade 1x to 2x if 2x found later
    contactsQRP := make(map[string]ProcessedQSO)
    for _, qso := range adiOrder {
        if qso.QRPx1QSO {
            key := qso.SKCCNr + "_" + qso.Band
            existing, exists := contactsQRP[key]
            if !exists {
                // First QSO for this member/band combination
                contactsQRP[key] = qso
            } else if qso.QRPx2QSO && !existing.QRPx2QSO {
                // Upgrade from QRP 1x to QRP 2x if we find a 2x QSO for same member/band
                contactsQRP[key] = qso
            }
            // Otherwise keep the first QSO (don't overwrite)
        }
    }
    awards["QRP"] = contactsQRP

    // DX - use chronological order (oldest QSO first)
    contactsDXC := make(map[string]ProcessedQSO)
    contactsDXQ := make(map[string]ProcessedQSO)
    for _, qso := range chrono {
        if qso.DXCQSO {
            if _, exists := contactsDXC[qso.DXCode]; !exists {
                contactsDXC[qso.DXCode] = qso
            }
        }
        if qso.DXQQSO {
            if _, exists := contactsDXQ[qso.SKCCNr]; !exists {
                contactsDXQ[qso.SKCCNr] = qso
            }
        }
    }
    awards["DXC"] = contactsDXC
    awards["DXQ"] = contactsDXQ

    // RC - Process in ADI file order with back-to-back duplicate handling
    // Allow multiple QSOs with same member
    // BUT if same member appears consecutively in ADI file, keep only longest
    contactsRC := make(map[string]ProcessedQSO)
    var lastRCMember string
    var lastRCKey string
    var lastRCMins int

    for _, qso := range adiOrder {
        if qso.RagChewQSO {
            // Use unique key: member_date_time
            rcKey := qso.SKCCNr + "_" + qso.QSODate + "_" + qso.TimeOn

            if qso.SKCCNr != lastRCMember {
                // Different member - always add
                contactsRC[rcKey] = qso
                lastRCMember = qso.SKCCNr
                lastRCKey = rcKey
                lastRCMins = qso.RagChewMins
            } else {
                // Same member as previous - only keep if longer
                if qso.RagChewMins > lastRCMins {
                    // Remove previous and add this one
                    delete(contactsRC, lastRCKey)
                    contactsRC[rcKey] = qso
                    lastRCKey = rcKey
                    lastRCMins = qso.RagChewMins
                }
                // If not longer, skip this QSO (keep the previous one)
            }
        }
    }
    awards["RC"] = contactsRC

    // TKA - use ADI file order
    contactsTKASK := make(map[string]ProcessedQSO)
    contactsTKABUG := make(map[string]ProcessedQSO)
    contactsTKASS := make(map[string]ProcessedQSO)

    for _, qso := range adiOrder {
        if qso.TKAQSO {
            kt := strings.ToUpper(qso.KeyType)
            switch kt {
            case "SK", "S":
                if _, exists := contactsTKASK[qso.SKCCNr]; !exists {
                    contactsTKASK[qso.SKCCNr] = qso
                }
            case "BUG", "B":
                if _, exists := contactsTKABUG[qso.SKCCNr]; !exists {
                    contactsTKABUG[qso.SKCCNr] = qso
                }
            case "SS":
                if _, exists := contactsTKASS[qso.SKCCNr]; !exists {
                    contactsTKASS[qso.SKCCNr] = qso
                }
            }
        }
    }

    // TKA duplicate removal (Xojo logic)
    removeTKADuplicates(contactsTKASK, contactsTKABUG, contactsTKASS)

    awards["TKA_SK"] = contactsTKASK
    awards["TKA_BUG"] = contactsTKABUG
    awards["TKA_SS"] = contactsTKASS

    // K3Y processing
    // Process K3Y QSOs separately as they have special handling
    k3yContacts := make(map[string]map[int]string)
    if slices.Contains(config.Goals, "K3Y") {
        // K3Y year range: Jan 2 to Feb 1 (8-digit date format to match QSO dates)
        k3yStart := fmt.Sprintf("%d0102", config.K3YYear)
        k3yEnd := fmt.Sprintf("%d0201", config.K3YYear)

        // K3Y regex pattern: r'.*?(?:K3Y|SKM)[\/-]([0-9]|KH6|KL7|KP4|AF|AS|EU|NA|OC|SA)'
        k3yRegex := regexp.MustCompile(`(?i)(?:K3Y|SKM)[\/-]([0-9]|KH6|KL7|KP4|AF|AS|EU|NA|OC|SA)`)

        for _, qso := range adiOrder {
            // K3Y processing - date filtering
            if qso.QSODate >= k3yStart && qso.QSODate < k3yEnd {
                if matches := k3yRegex.FindStringSubmatch(qso.Comment); matches != nil {
                    suffix := strings.ToUpper(matches[1])

                    // Use whichARRLBand to determine band name
                    // FREQ field is in MHz, need to convert to kHz
                    if qso.Freq != "" {
                        freqMHz, err := strconv.ParseFloat(qso.Freq, 64)
                        if err == nil {
                            freqKHz := freqMHz * 1000
                            if band := whichARRLBand(freqKHz); band > 0 {
                                if k3yContacts[suffix] == nil {
                                    k3yContacts[suffix] = make(map[int]string)
                                }
                                k3yContacts[suffix][band] = qso.Call
                            }
                        }
                    }
                }
            }
        }
    }
    awards["K3Y"] = k3yContacts

    return awards
}

func removeTKADuplicates(sk, bug, ss map[string]ProcessedQSO) {
    // Find members in multiple dictionaries
    allMembers := make(map[string]int)
    for k := range sk {
        allMembers[k]++
    }
    for k := range bug {
        allMembers[k]++
    }
    for k := range ss {
        allMembers[k]++
    }

    // Extract duplicates and sort in ascending order to match Xojo's
    // database iteration (no ORDER BY = insertion/chronological order)
    var duplicates []string
    for member, count := range allMembers {
        if count > 1 {
            duplicates = append(duplicates, member)
        }
    }
    sort.Strings(duplicates) // Sort ascending to match Xojo behavior

    // Process duplicates in sorted order
    for _, member := range duplicates {
        count := allMembers[member]

        // Member in multiple dicts - remove from largest
        for count > 1 {
            _, inSK := sk[member]
            _, inBUG := bug[member]
            _, inSS := ss[member]

            // Determine which to remove from
            var removeFrom string
            if inSK && inBUG && inSS {
                if len(bug) >= len(sk) && len(bug) >= len(ss) {
                    removeFrom = "BUG"
                } else if len(sk) >= len(ss) {
                    removeFrom = "SK"
                } else {
                    removeFrom = "SS"
                }
            } else if inSK && inBUG {
                if len(bug) >= len(sk) {
                    removeFrom = "BUG"
                } else {
                    removeFrom = "SK"
                }
            } else if inSK && inSS {
                if len(sk) > len(ss) {
                    removeFrom = "SK"
                } else {
                    removeFrom = "SS"
                }
            } else if inBUG && inSS {
                if len(bug) >= len(ss) {
                    removeFrom = "BUG"
                } else {
                    removeFrom = "SS"
                }
            }

            switch removeFrom {
            case "SK":
                delete(sk, member)
            case "BUG":
                delete(bug, member)
            case "SS":
                delete(ss, member)
            }
            count--
        }
    }
}

// ============================================================================
// OUTPUT FILES
// ============================================================================

func writeAwardFiles(awards map[string]any, ap *AwardProcessor) {
    os.MkdirAll("QSOs", 0755)

    // Write skipped QSOs file
    if len(ap.qsosSkipped) > 0 {
        writeSkippedQSOs(ap.qsosSkipped)
    }

    // Write Need SKCC Numbers file
    if len(ap.qsosNeedSKCC) > 0 {
        writeNeedSKCCFile(ap.qsosNeedSKCC)
    }

    // Write Inspect file
    if len(ap.qsosAutoMatched) > 0 {
        writeInspectFile(ap.qsosAutoMatched, awards)
    }

    // C, T, S awards
    writeCTSAward("C", awards["C"].(map[string]ProcessedQSO))
    writeCTSAward("T", awards["T"].(map[string]ProcessedQSO))
    writeCTSAward("S", awards["S"].(map[string]ProcessedQSO))

    // WAS awards - states output in alphabetical order with suffix and callsign substitution
    writeWASAward("WAS", awards["WAS"].(map[string]ProcessedQSO), ap.memberDB)
    writeWASAward("WAS-C", awards["WAS-C"].(map[string]ProcessedQSO), ap.memberDB)
    writeWASAward("WAS-T", awards["WAS-T"].(map[string]ProcessedQSO), ap.memberDB)
    writeWASAward("WAS-S", awards["WAS-S"].(map[string]ProcessedQSO), ap.memberDB)

    // Prefix award
    writePrefixAward(awards["P"].(map[string]ProcessedQSO))

    // QRP award
    writeQRPAward(awards["QRP"].(map[string]ProcessedQSO))

    // DX awards
    writeDXAwards(awards["DXC"].(map[string]ProcessedQSO), awards["DXQ"].(map[string]ProcessedQSO))

    // RC award
    writeRCAward(awards["RC"].(map[string]ProcessedQSO))

    // TKA award
    writeTKAAward(
        awards["TKA_SK"].(map[string]ProcessedQSO),
        awards["TKA_BUG"].(map[string]ProcessedQSO),
        awards["TKA_SS"].(map[string]ProcessedQSO),
    )
}

func writeSkippedQSOs(skipped []string) {
    filename := filepath.Join("QSOs", config.MyCallsign+"-Skipped_QSOs.txt")
    file, err := os.Create(filename)
    if err != nil {
        return
    }
    defer file.Close()

    fmt.Fprintf(file, "Skipped QSO Log Entries for %s\n", config.MyCallsign)
    fmt.Fprintln(file, strings.Repeat("=", 70))
    fmt.Fprintln(file)
    fmt.Fprintln(file, "In addition to any non-CW QSOs or QSOs logged before you were a SKCC member,")
    fmt.Fprintln(file, "the following QSOs were not valid:")
    fmt.Fprintln(file)

    for _, s := range skipped {
        fmt.Fprintln(file, s)
    }

    fmt.Fprintf(file, "\nTotal skipped: %d\n", len(skipped))
    fmt.Fprintln(file, "\nEnd of List")
}

func writeNeedSKCCFile(entries []NeedSKCCEntry) {
    filename := filepath.Join("QSOs", config.MyCallsign+"-Need_SKCC_Numbers.txt")
    file, err := os.Create(filename)
    if err != nil {
        return
    }
    defer file.Close()

    fmt.Fprintf(file, "QSOs Requiring SKCC Numbers for %s\n", config.MyCallsign)
    fmt.Fprintln(file, strings.Repeat("=", 70))
    fmt.Fprintln(file)
    fmt.Fprintln(file, "These QSOs are with SKCC members but require SKCC numbers in your log")
    fmt.Fprintln(file, "to count for awards (multiple members have held these callsigns).")
    fmt.Fprintln(file)

    // Sort by date descending
    sort.Slice(entries, func(i, j int) bool {
        if entries[i].Date != entries[j].Date {
            return entries[i].Date > entries[j].Date
        }
        return entries[i].Time > entries[j].Time
    })

    for _, e := range entries {
        fmt.Fprintln(file, e.Entry)
    }

    fmt.Fprintf(file, "\nTotal QSOs needing SKCC numbers: %d\n", len(entries))
    fmt.Fprintln(file, "\nEnd of List")
}

func writeInspectFile(autoMatched []AutoMatchEntry, awards map[string]any) {
    filename := filepath.Join("QSOs", config.MyCallsign+"-Inspect_QSOs.txt")
    file, err := os.Create(filename)
    if err != nil {
        return
    }
    defer file.Close()

    fmt.Fprintln(file, "SKCC Skimmer - QSOs Requiring Inspection")
    fmt.Fprintf(file, "Generated: %s\n", time.Now().UTC().Format("20060102 150405Z"))
    fmt.Fprintf(file, "Callsign: %s\n", config.MyCallsign)
    fmt.Fprintln(file)
    fmt.Fprintln(file, "WARNING: The following QSOs have no SKCC number in your log but were")
    fmt.Fprintln(file, "automatically matched to SKCC members. Please verify these are valid SKCC QSOs.")
    fmt.Fprintln(file)
    fmt.Fprintln(file, "If these are POTA, contest, or casual QSOs, they should NOT count for SKCC awards.")
    fmt.Fprintln(file, "To fix: Add SKCC numbers only to QSOs where numbers were actually exchanged.")
    fmt.Fprintln(file)
    fmt.Fprintln(file, "QSOs Automatically Matched (No SKCC Field in Log):")
    fmt.Fprintln(file, strings.Repeat("=", 70))
    fmt.Fprintln(file)

    contactsC := awards["C"].(map[string]ProcessedQSO)
    contactsT := awards["T"].(map[string]ProcessedQSO)
    contactsS := awards["S"].(map[string]ProcessedQSO)

    for _, am := range autoMatched {
        dateStr := formatDate(am.QSO.QSODate)
        timeStr := formatTime(am.QSO.TimeOn)

        fmt.Fprintf(file, "Date: %s     Time: %s     Call: %s\n", dateStr, timeStr, am.QSO.Call)
        fmt.Fprintf(file, "  Band: %s     Mode: %s", am.QSO.Band, am.QSO.Mode)
        if am.QSO.Comment != "" {
            comment := am.QSO.Comment
            if len(comment) > 50 {
                comment = comment[:50]
            }
            fmt.Fprintf(file, "     Comment: %s", comment)
        }
        fmt.Fprintln(file)
        fmt.Fprintf(file, "  Auto-matched to: SKCC #%s (%s)\n", am.Member.SKCCNumber, am.Member.Name)

        // Show which awards
        var awardsAffected []string
        if _, exists := contactsC[am.SKCCNr]; exists {
            awardsAffected = append(awardsAffected, "C")
        }
        if _, exists := contactsT[am.SKCCNr]; exists {
            awardsAffected = append(awardsAffected, "T")
        }
        if _, exists := contactsS[am.SKCCNr]; exists {
            awardsAffected = append(awardsAffected, "S")
        }
        if len(awardsAffected) > 0 {
            fmt.Fprintf(file, "  Counting toward: %s\n", strings.Join(awardsAffected, ", "))
        }
        fmt.Fprintln(file)
    }

    fmt.Fprintln(file, "\nNote: Current version counts these for compatibility with SKCCLogger v03.01.04.")
    fmt.Fprintln(file, "Future versions may require SKCC numbers to be explicitly logged.")
}

func writeCTSAward(name string, contacts map[string]ProcessedQSO) {
    if len(contacts) == 0 {
        return
    }

    filename := filepath.Join("QSOs", config.MyCallsign+"-"+name+".txt")
    file, err := os.Create(filename)
    if err != nil {
        return
    }
    defer file.Close()

    // Sort by date, then time (matching Xojo: ORDER BY Log_QSO_DATE, Log_TIME_ON)
    var sorted []ProcessedQSO
    for _, c := range contacts {
        sorted = append(sorted, c)
    }
    sort.Slice(sorted, func(i, j int) bool {
        if sorted[i].QSODate != sorted[j].QSODate {
            return sorted[i].QSODate < sorted[j].QSODate
        }
        return sorted[i].TimeOn < sorted[j].TimeOn
    })

    for i, qso := range sorted {
        dateStr := formatDate(qso.QSODate)
        band := strings.TrimSuffix(qso.Band, "M")
        band = strings.TrimSuffix(band, "m")
        nameStr := qso.Name
        if len(nameStr) > 12 {
            nameStr = nameStr[:12]
        }
        fmt.Fprintf(file, "%-6d %11s   %-13s %-8s %-12s %-12s %2s\n",
            i+1, dateStr, qso.Call, qso.SKCCNr, nameStr, qso.State, band)
    }
}

// getWASDisplayData returns the callsign and SKCC number with suffix for WAS award display
// This matches Xojo behavior of substituting primary callsign and adding suffix
func getWASDisplayData(qso ProcessedQSO, members map[string]*Member) (string, string) {
    // Look up the member to get their award dates and primary callsign
    member, exists := members[qso.SKCCNr]
    if !exists {
        return qso.Call, qso.SKCCNr
    }

    // Use member's primary callsign (matching Xojo behavior)
    displayCall := member.Callsign
    if displayCall == "" {
        displayCall = qso.Call
    }

    // Recreate suffix as it would have appeared at the time of the QSO
    skccWithSuffix := qso.SKCCNr
    qsoDate := qso.QSODate

    // Normalize dates (first 8 chars: YYYYMMDD)
    centDate := member.CDate
    if len(centDate) > 8 {
        centDate = centDate[:8]
    }
    tribDate := member.TDate
    if len(tribDate) > 8 {
        tribDate = tribDate[:8]
    }
    senDate := member.SDate
    if len(senDate) > 8 {
        senDate = senDate[:8]
    }

    // Add suffix based on member's award dates at the time of QSO
    if centDate != "" && qsoDate >= centDate {
        skccWithSuffix = qso.SKCCNr + "C"
    }
    if tribDate != "" && qsoDate >= tribDate {
        skccWithSuffix = qso.SKCCNr + "T"
    }
    if senDate != "" && qsoDate >= senDate {
        skccWithSuffix = qso.SKCCNr + "S"
    }

    return displayCall, skccWithSuffix
}

func writeWASAward(name string, contacts map[string]ProcessedQSO, members map[string]*Member) {
    filename := filepath.Join("QSOs", config.MyCallsign+"-"+name+".txt")
    file, err := os.Create(filename)
    if err != nil {
        return
    }
    defer file.Close()

    // Write states in alphabetical order (matching Xojo behavior)
    for _, state := range usStates {
        if qso, exists := contacts[state]; exists {
            // Get display callsign and SKCC number with suffix
            displayCall, skccWithSuffix := getWASDisplayData(qso, members)

            dateStr := formatDate(qso.QSODate)
            nameStr := qso.Name
            if len(nameStr) > 12 {
                nameStr = nameStr[:12]
            }
            // Add leading space to match Xojo format
            fmt.Fprintf(file, " %-8s %-12s %-9s %-13s %-16s %s\n",
                qso.State, displayCall, skccWithSuffix, nameStr, dateStr, qso.Band)
        } else {
            fmt.Fprintln(file, state)
        }
    }
}

// formatWithCommas formats a number with thousand separators
func formatWithCommas(n int) string {
    s := strconv.Itoa(n)
    if len(s) <= 3 {
        return s
    }

    var result strings.Builder
    for i, digit := range s {
        if i > 0 && (len(s)-i)%3 == 0 {
            result.WriteRune(',')
        }
        result.WriteRune(digit)
    }
    return result.String()
}

func writePrefixAward(contacts map[string]ProcessedQSO) {
    if len(contacts) == 0 {
        return
    }

    filename := filepath.Join("QSOs", config.MyCallsign+"-P.txt")
    file, err := os.Create(filename)
    if err != nil {
        return
    }
    defer file.Close()

    // Sort by prefix
    var sorted []ProcessedQSO
    for _, c := range contacts {
        sorted = append(sorted, c)
    }
    sort.Slice(sorted, func(i, j int) bool {
        return sorted[i].Pfx < sorted[j].Pfx
    })

    totalPoints := 0
    for i, qso := range sorted {
        pts, _ := strconv.Atoi(qso.PfxPts)
        totalPoints += pts
        dateStr := formatDate(qso.QSODate)
        band := strings.TrimSuffix(qso.Band, "M")
        band = strings.TrimSuffix(band, "m")
        nameStr := qso.Name
        if len(nameStr) > 12 {
            nameStr = nameStr[:12]
        }
        // Format cumulative points with thousand separators
        totalPtsStr := formatWithCommas(totalPoints)
        // Use PfxCall (normalized callsign without portable indicators) to match Xojo
        fmt.Fprintf(file, "%5d  %s   %-13s %-8d %-12s %-12s %3s  %10s\n",
            i+1, dateStr, qso.PfxCall, pts, nameStr, qso.Pfx, band, totalPtsStr)
    }
}

func writeQRPAward(contacts map[string]ProcessedQSO) {
    if len(contacts) == 0 {
        return
    }

    // Separate 1x and 2x
    var qrp1x, qrp2x []ProcessedQSO
    for _, qso := range contacts {
        qrp1x = append(qrp1x, qso)
        if qso.QRPx2QSO {
            qrp2x = append(qrp2x, qso)
        }
    }

    // Sort by date, then time (matching Xojo: ORDER BY Log_QSO_DATE, Log_TIME_ON)
    sort.Slice(qrp1x, func(i, j int) bool {
        if qrp1x[i].QSODate != qrp1x[j].QSODate {
            return qrp1x[i].QSODate < qrp1x[j].QSODate
        }
        return qrp1x[i].TimeOn < qrp1x[j].TimeOn
    })
    sort.Slice(qrp2x, func(i, j int) bool {
        if qrp2x[i].QSODate != qrp2x[j].QSODate {
            return qrp2x[i].QSODate < qrp2x[j].QSODate
        }
        return qrp2x[i].TimeOn < qrp2x[j].TimeOn
    })

    // Write 1x file
    if len(qrp1x) > 0 {
        filename := filepath.Join("QSOs", config.MyCallsign+"-QRP-1x.txt")
        file, _ := os.Create(filename)
        defer file.Close()

        totalPts := 0.0
        for i, qso := range qrp1x {
            pts := qrpBandPoints[qso.Band]
            totalPts += pts
            fmt.Fprintf(file, "%4d %8s %-12s %-6s %6.1f %8.1f\n",
                i+1, qso.SKCCNr, qso.Call, qso.Band, pts, totalPts)
        }
        fmt.Fprintf(file, "\nTotal Points: %.1f (Need: 300)\n", totalPts)
        fmt.Fprintf(file, "Progress: %.1f%%\n", totalPts/3.0)
    }

    // Write 2x file
    if len(qrp2x) > 0 {
        filename := filepath.Join("QSOs", config.MyCallsign+"-QRP-2x.txt")
        file, _ := os.Create(filename)
        defer file.Close()

        totalPts := 0.0
        for i, qso := range qrp2x {
            pts := qrpBandPoints[qso.Band]
            totalPts += pts
            fmt.Fprintf(file, "%4d %8s %-12s %-6s %6.1f %8.1f\n",
                i+1, qso.SKCCNr, qso.Call, qso.Band, pts, totalPts)
        }
        fmt.Fprintf(file, "\nTotal Points: %.1f (Need: 150)\n", totalPts)
        fmt.Fprintf(file, "Progress: %.1f%%\n", totalPts*2.0/3.0)
    }
}

func writeDXAwards(dxc, dxq map[string]ProcessedQSO) {
    // DXC file
    if len(dxc) > 0 {
        filename := filepath.Join("QSOs", config.MyCallsign+"-DXC.txt")
        file, _ := os.Create(filename)
        defer file.Close()

        fmt.Fprintln(file, "  #  QSO Date    Callsign     Name        SKCC#   DXCC  Country              Band")
        fmt.Fprintln(file, strings.Repeat("-", 85))

        var sorted []ProcessedQSO
        for _, qso := range dxc {
            sorted = append(sorted, qso)
        }
        sort.Slice(sorted, func(i, j int) bool {
            return sorted[i].DXCode < sorted[j].DXCode
        })

        for i, qso := range sorted {
            dateStr := formatDate(qso.QSODate)
            nameStr := qso.Name
            if len(nameStr) > 10 {
                nameStr = nameStr[:10]
            }
            country := "Unknown"
            fmt.Fprintf(file, "%3d  %s  %-12s %-11s %-7s %4s  %-20s %s\n",
                i+1, dateStr, qso.Call, nameStr, qso.SKCCNr, qso.DXCC, country, qso.Band)
        }

        fmt.Fprintln(file, strings.Repeat("-", 85))
        fmt.Fprintf(file, "Total Countries: %d (Need: 100)\n", len(dxc))
        fmt.Fprintf(file, "Progress: %.1f%%\n", float64(len(dxc)))
    }

    // DXQ file
    if len(dxq) > 0 {
        filename := filepath.Join("QSOs", config.MyCallsign+"-DXQ.txt")
        file, _ := os.Create(filename)
        defer file.Close()

        fmt.Fprintln(file, "  #  QSO Date    Callsign     Name        SKCC#   DXCC  Country              Band")
        fmt.Fprintln(file, strings.Repeat("-", 85))

        var sorted []ProcessedQSO
        for _, qso := range dxq {
            sorted = append(sorted, qso)
        }
        sort.Slice(sorted, func(i, j int) bool {
            if sorted[i].QSODate != sorted[j].QSODate {
                return sorted[i].QSODate < sorted[j].QSODate
            }
            return sorted[i].TimeOn < sorted[j].TimeOn
        })

        for i, qso := range sorted {
            dateStr := formatDate(qso.QSODate)
            nameStr := qso.Name
            if len(nameStr) > 10 {
                nameStr = nameStr[:10]
            }
            country := "Unknown"
            fmt.Fprintf(file, "%3d  %s  %-12s %-11s %-7s %4s  %-20s %s\n",
                i+1, dateStr, qso.Call, nameStr, qso.SKCCNr, qso.DXCC, country, qso.Band)
        }

        fmt.Fprintln(file, strings.Repeat("-", 85))
        fmt.Fprintf(file, "Total Foreign Member QSOs: %d (Need: 100)\n", len(dxq))
        fmt.Fprintf(file, "Progress: %.1f%%\n", float64(len(dxq)))
    }
}

func writeRCAward(contacts map[string]ProcessedQSO) {
    if len(contacts) == 0 {
        return
    }

    filename := filepath.Join("QSOs", config.MyCallsign+"-RC.txt")
    file, _ := os.Create(filename)
    defer file.Close()

    totalMins := 0
    for _, qso := range contacts {
        totalMins += qso.RagChewMins
    }

    fmt.Fprintf(file, "Total QSOs: %d\n", len(contacts))
    fmt.Fprintf(file, "Total Minutes: %d\n", totalMins)
    fmt.Fprintln(file)
    fmt.Fprintln(file, "Date        Call         SKCC#     Name         Band  Minutes")
    fmt.Fprintln(file, strings.Repeat("-", 60))

    var sorted []ProcessedQSO
    for _, qso := range contacts {
        sorted = append(sorted, qso)
    }
    sort.Slice(sorted, func(i, j int) bool {
        if sorted[i].QSODate != sorted[j].QSODate {
            return sorted[i].QSODate < sorted[j].QSODate
        }
        return sorted[i].TimeOn < sorted[j].TimeOn
    })

    for _, qso := range sorted {
        dateStr := formatDate(qso.QSODate)
        band := strings.TrimSuffix(qso.Band, "M")
        band = strings.TrimSuffix(band, "m")
        nameStr := qso.Name
        if len(nameStr) > 12 {
            nameStr = nameStr[:12]
        }
        fmt.Fprintf(file, "%s  %-12s %-8s %-12s %3s  %4d\n",
            dateStr, qso.Call, qso.SKCCNr, nameStr, band, qso.RagChewMins)
    }

    fmt.Fprintln(file, strings.Repeat("-", 60))
    fmt.Fprintf(file, "TOTAL MINUTES: %d\n", totalMins)
}

func writeTKAAward(sk, bug, ss map[string]ProcessedQSO) {
    if len(sk) == 0 && len(bug) == 0 && len(ss) == 0 {
        return
    }

    filename := filepath.Join("QSOs", config.MyCallsign+"-TKA.txt")
    file, _ := os.Create(filename)
    defer file.Close()

    fmt.Fprintln(file, "Triple Key Award - Need 100 each of SK, BUG, SS from 300 unique members")
    fmt.Fprintln(file)

    writeKeyType := func(name string, contacts map[string]ProcessedQSO) {
        if len(contacts) == 0 {
            return
        }
        fmt.Fprintf(file, "%s Contacts (%d):\n", name, len(contacts))
        fmt.Fprintln(file, strings.Repeat("-", 60))

        var sorted []ProcessedQSO
        for _, qso := range contacts {
            sorted = append(sorted, qso)
        }
        // Sort by date, then time (matching standard chronological order)
        sort.Slice(sorted, func(i, j int) bool {
            if sorted[i].QSODate != sorted[j].QSODate {
                return sorted[i].QSODate < sorted[j].QSODate
            }
            return sorted[i].TimeOn < sorted[j].TimeOn
        })

        for i, qso := range sorted {
            dateStr := formatDate(qso.QSODate)
            // Use CallPri (member's current primary callsign) not Call (ADI callsign)
            // This matches Xojo which uses log_call_pri from member database
            fmt.Fprintf(file, "%-6d %s  %-13s %-8s %-12s %-12s %s\n",
                i+1, dateStr, qso.CallPri, qso.SKCCNr, qso.Name, qso.State, name)
        }
        fmt.Fprintln(file)
    }

    writeKeyType("BUG", bug)
    writeKeyType("SK", sk)
    writeKeyType("SS", ss)

    // Calculate unique
    allMembers := make(map[string]bool)
    for k := range sk {
        allMembers[k] = true
    }
    for k := range bug {
        allMembers[k] = true
    }
    for k := range ss {
        allMembers[k] = true
    }

    fmt.Fprintln(file, strings.Repeat("=", 70))
    fmt.Fprintf(file, "SUMMARY: SK:%d BUG:%d SS:%d Total unique:%d/300\n",
        len(sk), len(bug), len(ss), len(allMembers))
}

// ============================================================================
// PROGRESS DISPLAY
// ============================================================================

func printConfigSummary(config *Config) {
    fmt.Println()
    // Goals
    if len(config.Goals) > 0 {
        fmt.Printf("GOALS: %s\n", strings.Join(config.Goals, ", "))
    }
    // Targets
    if len(config.Targets) > 0 {
        fmt.Printf("TARGETS: %s\n", strings.Join(config.Targets, ", "))
    }
    // Bands
    if len(config.Bands) > 0 {
        bandStrs := make([]string, len(config.Bands))
        for i, b := range config.Bands {
            bandStrs[i] = strconv.Itoa(b)
        }
        fmt.Printf("BANDS: %s\n", strings.Join(bandStrs, ", "))
    }
}

func printFYIMessages(awards map[string]any, rosters *Rosters, config *Config, members map[string]*Member) {
    myMember := members[config.MyCallsign]
    if myMember == nil {
        return
    }

    myNumber := myMember.PlainNumber

    contactsC := awards["C"].(map[string]ProcessedQSO)
    contactsT := awards["T"].(map[string]ProcessedQSO)
    contactsS := awards["S"].(map[string]ProcessedQSO)
    contactsP := awards["P"].(map[string]ProcessedQSO)
    contactsWAS := awards["WAS"].(map[string]ProcessedQSO)
    contactsWASC := awards["WAS-C"].(map[string]ProcessedQSO)
    contactsWAST := awards["WAS-T"].(map[string]ProcessedQSO)
    contactsWASS := awards["WAS-S"].(map[string]ProcessedQSO)
    contactsQRP := awards["QRP"].(map[string]ProcessedQSO)
    contactsDXC := awards["DXC"].(map[string]ProcessedQSO)
    contactsDXQ := awards["DXQ"].(map[string]ProcessedQSO)
    contactsRC := awards["RC"].(map[string]ProcessedQSO)
    contactsTKASK := awards["TKA_SK"].(map[string]ProcessedQSO)
    contactsTKABUG := awards["TKA_BUG"].(map[string]ProcessedQSO)
    contactsTKASS := awards["TKA_SS"].(map[string]ProcessedQSO)

    // C award FYI
    if slices.Contains(config.Goals, "C") {
        cCount := len(contactsC)
        if cCount >= 100 {
            cLevel := calculateAwardLevel(cCount, 100)
            if myMember.CDate != "" {
                if awardLevel, exists := rosters.Centurion[myNumber]; exists {
                    if cLevel > awardLevel {
                        cOrCx := "C"
                        if awardLevel > 1 {
                            cOrCx = fmt.Sprintf("Cx%d", awardLevel)
                        }
                        nextLevelName := "C"
                        if cLevel > 1 {
                            nextLevelName = fmt.Sprintf("Cx%d", cLevel)
                        }
                        fmt.Printf("FYI: You qualify for %s but have only applied for %s.\n", nextLevelName, cOrCx)
                    }
                }
            } else {
                if _, exists := rosters.Centurion[myNumber]; !exists && cLevel >= 1 {
                    fmt.Println("FYI: You qualify for C but have not yet applied for it.")
                }
            }
        }
    }

    // T award FYI
    if slices.Contains(config.Goals, "T") {
        tCount := len(contactsT)
        if tCount >= 50 {
            tLevel := calculateAwardLevel(tCount, 50)
            if myMember.CDate == "" {
                if tLevel > 0 {
                    fmt.Println("NOTE: Tribune award requires Centurion first. Apply for C before T.")
                }
            } else if myMember.TDate != "" {
                if awardLevel, exists := rosters.Tribune[myNumber]; exists {
                    if tLevel > awardLevel {
                        tOrTx := "T"
                        if awardLevel > 1 {
                            tOrTx = fmt.Sprintf("Tx%d", awardLevel)
                        }
                        nextLevelName := "T"
                        if tLevel > 1 {
                            nextLevelName = fmt.Sprintf("Tx%d", tLevel)
                        }
                        fmt.Printf("FYI: You qualify for %s but have only applied for %s.\n", nextLevelName, tOrTx)
                    }
                }
            } else {
                if _, exists := rosters.Tribune[myNumber]; !exists && tLevel >= 1 {
                    fmt.Println("FYI: You qualify for T but have not yet applied for it.")
                }
            }
        }
    }

    // S award FYI
    if slices.Contains(config.Goals, "S") {
        sCount := len(contactsS)
        tribuneContacts := len(contactsT)
        if tribuneContacts < 400 {
            if sCount >= 200 {
                fmt.Printf("NOTE: Senator award requires Tribune x8 (400 contacts) first. Currently have %d Tribune contacts.\n", tribuneContacts)
            }
        } else if sCount >= 200 {
            sLevel := calculateAwardLevel(sCount, 200)
            if myMember.SDate != "" {
                if awardLevel, exists := rosters.Senator[myNumber]; exists {
                    if sLevel > awardLevel {
                        sOrSx := "S"
                        if awardLevel > 1 {
                            sOrSx = fmt.Sprintf("Sx%d", awardLevel)
                        }
                        nextLevelName := "S"
                        if sLevel > 1 {
                            nextLevelName = fmt.Sprintf("Sx%d", sLevel)
                        }
                        fmt.Printf("FYI: You qualify for %s but have only applied for %s.\n", nextLevelName, sOrSx)
                    }
                }
            } else {
                if _, exists := rosters.Senator[myNumber]; !exists && sLevel >= 1 {
                    fmt.Println("FYI: You qualify for S but have not yet applied for it.")
                }
            }
        }
    }

    // WAS variants FYI
    if slices.Contains(config.Goals, "WAS") {
        if len(contactsWAS) == len(usStates) {
            if _, exists := rosters.WAS[config.MyCallsign]; !exists {
                fmt.Println("FYI: You qualify for WAS but have not yet applied for it.")
            }
        }
    }
    if slices.Contains(config.Goals, "WAS-C") {
        if len(contactsWASC) == len(usStates) {
            if _, exists := rosters.WASC[config.MyCallsign]; !exists {
                fmt.Println("FYI: You qualify for WAS-C but have not yet applied for it.")
            }
        }
    }
    if slices.Contains(config.Goals, "WAS-T") {
        if len(contactsWAST) == len(usStates) {
            if _, exists := rosters.WAST[config.MyCallsign]; !exists {
                fmt.Println("FYI: You qualify for WAS-T but have not yet applied for it.")
            }
        }
    }
    if slices.Contains(config.Goals, "WAS-S") {
        if len(contactsWASS) == len(usStates) {
            if _, exists := rosters.WASS[config.MyCallsign]; !exists {
                fmt.Println("FYI: You qualify for WAS-S but have not yet applied for it.")
            }
        }
    }

    // Prefix FYI
    if slices.Contains(config.Goals, "P") {
        pTotal := 0
        for _, qso := range contactsP {
            pts, _ := strconv.Atoi(qso.PfxPts)
            pTotal += pts
        }
        if pTotal > 500000 {
            pLevel := getPrefixLevel(pTotal)
            if awardLevel, exists := rosters.Prefix[config.MyCallsign]; exists {
                if pLevel > awardLevel {
                    fmt.Printf("FYI: You qualify for Px%d but have only applied for Px%d.\n", pLevel, awardLevel)
                }
            } else if pLevel >= 1 {
                fmt.Printf("FYI: You qualify for Px%d but have not yet applied for it.\n", pLevel)
            }
        }
    }

    // DX FYI
    if slices.Contains(config.Goals, "DX") {
        // DXC
        dxcCount := len(contactsDXC)
        if dxcCount >= 10 {
            dxcLevel, _, _ := getDXLevel(dxcCount)
            if awardLevel, exists := rosters.DXC[myNumber]; exists {
                if dxcLevel > awardLevel {
                    fmt.Printf("FYI: You qualify for DXCx%d but have only applied for DXCx%d.\n", dxcLevel, awardLevel)
                }
            } else {
                fmt.Printf("FYI: You qualify for DXCx%d but have not yet applied for it.\n", dxcLevel)
            }
        }

        // DXQ
        dxqCount := len(contactsDXQ)
        if dxqCount >= 10 {
            dxqLevel, _, _ := getDXLevel(dxqCount)
            if awardLevel, exists := rosters.DXQ[myNumber]; exists {
                if dxqLevel > awardLevel {
                    fmt.Printf("FYI: You qualify for DXQx%d but have only applied for DXQx%d.\n", dxqLevel, awardLevel)
                }
            } else {
                fmt.Printf("FYI: You qualify for DXQx%d but have not yet applied for it.\n", dxqLevel)
            }
        }
    }

    // QRP FYI
    if slices.Contains(config.Goals, "QRP") {
        pts1x := 0.0
        pts2x := 0.0
        for _, qso := range contactsQRP {
            pts := qrpBandPoints[qso.Band]
            pts1x += pts
            if qso.QRPx2QSO {
                pts2x += pts
            }
        }

        // 1xQRP
        if pts1x >= 300 {
            qrp1xLevel := int(pts1x / 300)
            if awardLevel, exists := rosters.QRP1x[myNumber]; exists {
                if qrp1xLevel > awardLevel {
                    fmt.Printf("FYI: You qualify for 1xQRP x%d but have only applied for 1xQRP x%d.\n", qrp1xLevel, awardLevel)
                }
            } else {
                fmt.Printf("FYI: You qualify for 1xQRP x%d but have not yet applied for it.\n", qrp1xLevel)
            }
        }

        // 2xQRP
        if pts2x >= 150 {
            qrp2xLevel := int(pts2x / 150)
            if awardLevel, exists := rosters.QRP2x[myNumber]; exists {
                if qrp2xLevel > awardLevel {
                    fmt.Printf("FYI: You qualify for 2xQRP x%d but have only applied for 2xQRP x%d.\n", qrp2xLevel, awardLevel)
                }
            } else {
                fmt.Printf("FYI: You qualify for 2xQRP x%d but have not yet applied for it.\n", qrp2xLevel)
            }
        }
    }

    // TKA FYI
    if slices.Contains(config.Goals, "TKA") {
        skCount := len(contactsTKASK)
        bugCount := len(contactsTKABUG)
        ssCount := len(contactsTKASS)

        allMembers := make(map[string]bool)
        for k := range contactsTKASK {
            allMembers[k] = true
        }
        for k := range contactsTKABUG {
            allMembers[k] = true
        }
        for k := range contactsTKASS {
            allMembers[k] = true
        }
        uniqueTotal := len(allMembers)

        if skCount >= 100 && bugCount >= 100 && ssCount >= 100 && uniqueTotal >= 300 {
            if _, exists := rosters.TKA[myNumber]; !exists {
                fmt.Println("FYI: You qualify for TKA but have not yet applied for it.")
            }
        }
    }

    // RC FYI
    if slices.Contains(config.Goals, "RC") {
        totalMins := 0
        for _, qso := range contactsRC {
            totalMins += qso.RagChewMins
        }

        if totalMins >= 300 {
            rcLevel := getRCLevel(totalMins)
            if awardLevel, exists := rosters.RC[myNumber]; exists {
                if rcLevel > awardLevel {
                    levelName := "RC"
                    if rcLevel > 1 {
                        levelName = fmt.Sprintf("RCx%d", rcLevel)
                    }
                    appliedName := "RC"
                    if awardLevel > 1 {
                        appliedName = fmt.Sprintf("RCx%d", awardLevel)
                    }
                    fmt.Printf("FYI: You qualify for %s but have only applied for %s.\n", levelName, appliedName)
                }
            } else {
                levelName := "RC"
                if rcLevel > 1 {
                    levelName = fmt.Sprintf("RCx%d", rcLevel)
                }
                fmt.Printf("FYI: You qualify for %s but have not yet applied for it.\n", levelName)
            }
        }
    }
}

func printProgress(awards map[string]any, ap *AwardProcessor) {
    fmt.Println()
    fmt.Println("*** Awards Progress ***")

    contactsC := awards["C"].(map[string]ProcessedQSO)
    contactsT := awards["T"].(map[string]ProcessedQSO)
    contactsS := awards["S"].(map[string]ProcessedQSO)
    contactsP := awards["P"].(map[string]ProcessedQSO)
    contactsWAS := awards["WAS"].(map[string]ProcessedQSO)
    contactsWASC := awards["WAS-C"].(map[string]ProcessedQSO)
    contactsWAST := awards["WAS-T"].(map[string]ProcessedQSO)
    contactsWASS := awards["WAS-S"].(map[string]ProcessedQSO)
    contactsQRP := awards["QRP"].(map[string]ProcessedQSO)
    contactsDXC := awards["DXC"].(map[string]ProcessedQSO)
    contactsDXQ := awards["DXQ"].(map[string]ProcessedQSO)
    contactsRC := awards["RC"].(map[string]ProcessedQSO)
    contactsTKASK := awards["TKA_SK"].(map[string]ProcessedQSO)
    contactsTKABUG := awards["TKA_BUG"].(map[string]ProcessedQSO)
    contactsTKASS := awards["TKA_SS"].(map[string]ProcessedQSO)

    // C award
    cCount := len(contactsC)
    if cCount >= 100 {
        level := calculateAwardLevel(cCount, 100)
        nextLevel := level
        if level < 10 {
            nextLevel = level + 1
        } else {
            nextLevel = level + 5
        }
        nextLevelRequired := nextLevel * 100
        remaining := nextLevelRequired - cCount
        fmt.Printf("C: Have %s which qualifies for Cx%d. Cx%d requires %s (%s more)\n",
            formatComma(cCount), level, nextLevel, formatComma(nextLevelRequired), formatComma(remaining))
    } else {
        fmt.Printf("C: Have %d. C requires 100 (%d more)\n", cCount, 100-cCount)
    }

    // T award
    tCount := len(contactsT)
    if tCount >= 50 {
        level := calculateAwardLevel(tCount, 50)
        nextLevel := level
        if level < 10 {
            nextLevel = level + 1
        } else {
            nextLevel = level + 5
        }
        nextLevelRequired := nextLevel * 50
        remaining := nextLevelRequired - tCount
        fmt.Printf("T: Have %s which qualifies for Tx%d. Tx%d requires %s (%s more)\n",
            formatComma(tCount), level, nextLevel, formatComma(nextLevelRequired), formatComma(remaining))
    } else if members[config.MyCallsign].CDate != "" {
        fmt.Printf("T: Have %d. T requires 50 (%d more)\n", tCount, 50-tCount)
    } else {
        fmt.Println("T: Tribune award requires Centurion first. Apply for C before working toward T.")
    }

    // S award
    sCount := len(contactsS)
    if len(contactsT) >= 400 {
        if sCount >= 200 {
            level := calculateAwardLevel(sCount, 200)
            nextLevel := level
            if level < 10 {
                nextLevel = level + 1
            } else {
                nextLevel = level + 5
            }
            nextLevelRequired := nextLevel * 200
            remaining := nextLevelRequired - sCount
            fmt.Printf("S: Have %s which qualifies for Sx%d. Sx%d requires %s (%s more)\n",
                formatComma(sCount), level, nextLevel, formatComma(nextLevelRequired), formatComma(remaining))
        } else {
            fmt.Printf("S: Have %d. S requires 200 (%d more)\n", sCount, 200-sCount)
        }
    } else {
        fmt.Printf("S: Senator award requires Tribune x8 (400 contacts) first. Currently have %d Tribune contacts.\n", len(contactsT))
    }

    // Prefix
    pTotal := 0
    for _, qso := range contactsP {
        pts, _ := strconv.Atoi(qso.PfxPts)
        pTotal += pts
    }
    if pTotal > 500000 {
        level := getPrefixLevel(pTotal)
        nextLevel := level
        if level < 10 {
            nextLevel = level + 1
        } else {
            nextLevel = level + 5
        }

        // Calculate requirement for next level
        var nextLevelRequired int
        if nextLevel <= 10 {
            nextLevelRequired = nextLevel * 500000
        } else {
            nextLevelRequired = 5000000 + ((nextLevel - 10) / 5) * 2500000
        }

        remaining := nextLevelRequired - pTotal
        fmt.Printf("P: Have %s which qualifies for Px%d. Next level requires more than %s (%s more)\n",
            formatComma(pTotal), level, formatComma(nextLevelRequired), formatComma(remaining))
    } else {
        fmt.Printf("P: Have %s. Px1 requires more than 500000 (%s more)\n",
            formatComma(pTotal), formatComma(500000-pTotal))
    }

    // WAS
    if slices.Contains(config.Goals, "WAS") {
        printWASProgress("WAS", contactsWAS)
    }
    if slices.Contains(config.Goals, "WAS-C") {
        printWASProgress("WAS-C", contactsWASC)
    }
    if slices.Contains(config.Goals, "WAS-T") {
        printWASProgress("WAS-T", contactsWAST)
    }
    if slices.Contains(config.Goals, "WAS-S") {
        printWASProgress("WAS-S", contactsWASS)
    }

    // QRP
    if slices.Contains(config.Goals, "QRP") {
        printQRPProgress(contactsQRP)
    }

    // DX
    if slices.Contains(config.Goals, "DX") {
        printDXProgress(contactsDXC, contactsDXQ)
    }

    // RC
    if slices.Contains(config.Goals, "RC") {
        printRCProgress(contactsRC)
    }

    // TKA
    if slices.Contains(config.Goals, "TKA") {
        printTKAProgress(contactsTKASK, contactsTKABUG, contactsTKASS)
    }

    // BRAG
    if slices.Contains(config.Goals, "BRAG") {
        printBRAGProgress(ap)
    }

    // K3Y contact display
    if slices.Contains(config.Goals, "K3Y") {
        if k3yData, ok := awards["K3Y"].(map[string]map[int]string); ok {
            printK3YContacts(k3yData, config.K3YYear)
        }
    }

    fmt.Println()
}

// printK3YContacts prints the K3Y contacts table
func printK3YContacts(k3yData map[string]map[int]string, k3yYear int) {
    fmt.Println()
    fmt.Printf("K3Y %d\n", k3yYear)
    fmt.Println("========")
    fmt.Printf("%-8s|%-7s|%-7s|%-7s|%-7s|%-7s|%-7s|%-7s|%-7s|%-7s|%-7s|\n",
        "Station", "160m", "80m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m")
    fmt.Println()

    printStation := func(station string) {
        // Split on / or - to get suffix
        parts := strings.FieldsFunc(station, func(r rune) bool { return r == '/' || r == '-' })
        if len(parts) < 2 {
            return
        }
        suffix := parts[1]

        printBand := func(band int) {
            if bandData, exists := k3yData[suffix]; exists {
                if callsign, bandExists := bandData[band]; bandExists {
                    fmt.Printf(" %-6s|", callsign)
                    return
                }
            }
            fmt.Printf("%-7s|", "")
        }

        fmt.Printf("%-8s|", station)
        printBand(160)
        printBand(80)
        printBand(40)
        printBand(30)
        printBand(20)
        printBand(17)
        printBand(15)
        printBand(12)
        printBand(10)
        printBand(6)
        fmt.Println()
    }

    // Print in standard order
    printStation("K3Y/0")
    printStation("K3Y/1")
    printStation("K3Y/2")
    printStation("K3Y/3")
    printStation("K3Y/4")
    printStation("K3Y/5")
    printStation("K3Y/6")
    printStation("K3Y/7")
    printStation("K3Y/8")
    printStation("K3Y/9")
    printStation("K3Y/KH6")
    printStation("K3Y/KL7")
    printStation("K3Y/KP4")
    printStation("SKM-AF")
    printStation("SKM-AS")
    printStation("SKM-EU")
    printStation("SKM-NA")
    printStation("SKM-OC")
    printStation("SKM-SA")
}

// downloadRoster fetches a roster from the SKCC website
// Returns map of key->level (key is either SKCC# or callsign depending on roster type)
func downloadRoster(name, url string, useSKCCKey bool) (map[string]int, error) {
    fmt.Printf("Retrieving SKCC %s roster...\n", name)

    fullURL := SKCCBaseURL + url
    resp, err := http.Get(fullURL)
    if err != nil {
        return nil, fmt.Errorf("HTTP request failed: %w", err)
    }
    defer resp.Body.Close()

    if resp.StatusCode != 200 {
        return nil, fmt.Errorf("HTTP %d", resp.StatusCode)
    }

    roster := make(map[string]int)
    scanner := bufio.NewScanner(resp.Body)
    firstLine := true

    for scanner.Scan() {
        line := scanner.Text()

        // Skip header line
        if firstLine {
            firstLine = false
            continue
        }

        // Parse pipe-delimited format
        fields := strings.Split(line, "|")
        if len(fields) < 2 || fields[0] == "" {
            continue
        }

        // Extract level from cert (e.g., "RC x35" -> 35)
        cert := fields[0]
        level := 1
        if idx := strings.Index(cert, " x"); idx != -1 {
            levelStr := cert[idx+2:]
            if l, err := strconv.Atoi(levelStr); err == nil {
                level = l
            }
        }

        // Determine key: SKCC# (column 3) or Callsign (column 2)
        var key string
        if useSKCCKey {
            // C/T/S, DXC, DXQ, QRP, RC, TKA use SKCC number (column 3, index 2)
            if len(fields) > 2 && fields[2] != "" {
                key = fields[2]
            }
        } else {
            // WAS variants, Prefix use callsign (column 2, index 1)
            if len(fields) > 1 && fields[1] != "" {
                key = fields[1]
            }
        }

        if key != "" {
            roster[key] = level
        }
    }

    if err := scanner.Err(); err != nil {
        return nil, fmt.Errorf("scan error: %w", err)
    }

    return roster, nil
}

// downloadRosters downloads all rosters based on goals
func downloadRosters(config *Config) *Rosters {
    rosters := &Rosters{
        Centurion: make(map[string]int),
        Tribune:   make(map[string]int),
        Senator:   make(map[string]int),
        WAS:       make(map[string]int),
        WASC:      make(map[string]int),
        WAST:      make(map[string]int),
        WASS:      make(map[string]int),
        Prefix:    make(map[string]int),
        DXC:       make(map[string]int),
        DXQ:       make(map[string]int),
        QRP1x:     make(map[string]int),
        QRP2x:     make(map[string]int),
        TKA:       make(map[string]int),
        RC:        make(map[string]int),
    }

    // Define roster download tasks
    type rosterTask struct {
        name       string
        url        string
        useSKCCKey bool
        target     *map[string]int
    }

    var tasks []rosterTask

    // Build list of rosters to download based on goals
    for _, goal := range config.Goals {
        switch goal {
        case "C":
            tasks = append(tasks, rosterTask{"Centurion", "operating_awards/centurion/centurion_list.php", true, &rosters.Centurion})
        case "T":
            tasks = append(tasks, rosterTask{"Tribune", "operating_awards/tribune/tribune_list.php", true, &rosters.Tribune})
        case "S":
            tasks = append(tasks, rosterTask{"Senator", "operating_awards/senator/senator_list.php", true, &rosters.Senator})
        case "WAS":
            tasks = append(tasks, rosterTask{"WAS", "operating_awards/was/was_list.php", false, &rosters.WAS})
        case "WAS-C":
            tasks = append(tasks, rosterTask{"WAS-C", "operating_awards/was-c/was-c_list.php", false, &rosters.WASC})
        case "WAS-T":
            tasks = append(tasks, rosterTask{"WAS-T", "operating_awards/was-t/was-t_list.php", false, &rosters.WAST})
        case "WAS-S":
            tasks = append(tasks, rosterTask{"WAS-S", "operating_awards/was-s/was-s_list.php", false, &rosters.WASS})
        case "P":
            tasks = append(tasks, rosterTask{"PFX", "operating_awards/pfx/prefix_list.php", false, &rosters.Prefix})
        case "DX":
            tasks = append(tasks, rosterTask{"DXQ", "operating_awards/dx/dxq_list.php", true, &rosters.DXQ})
            tasks = append(tasks, rosterTask{"DXC", "operating_awards/dx/dxc_list.php", true, &rosters.DXC})
        case "QRP":
            tasks = append(tasks, rosterTask{"QRP 1x", "operating_awards/qrp_awards/qrp_x1_list.php", true, &rosters.QRP1x})
            tasks = append(tasks, rosterTask{"QRP 2x", "operating_awards/qrp_awards/qrp_x2_list.php", true, &rosters.QRP2x})
        case "TKA":
            tasks = append(tasks, rosterTask{"TKA", "operating_awards/triplekey/triplekey_list.php", true, &rosters.TKA})
        case "RC":
            tasks = append(tasks, rosterTask{"RC", "operating_awards/rag_chew/ragchew_list.php", true, &rosters.RC})
        }
    }

    // Download all rosters in parallel
    if len(tasks) > 0 {
        var wg sync.WaitGroup
        for _, task := range tasks {
            wg.Add(1)
            go func(t rosterTask) {
                defer wg.Done()
                if r, err := downloadRoster(t.name, t.url, t.useSKCCKey); err == nil {
                    *t.target = r
                }
            }(task)
        }
        wg.Wait()
    }

    return rosters
}

func formatComma(n int) string {
    s := strconv.Itoa(n)
    if len(s) <= 3 {
        return s
    }
    var result strings.Builder
    for i, c := range s {
        if i > 0 && (len(s)-i)%3 == 0 {
            result.WriteRune(',')
        }
        result.WriteRune(c)
    }
    return result.String()
}

func printWASProgress(name string, contacts map[string]ProcessedQSO) {
    count := len(contacts)
    if count == len(usStates) {
        fmt.Printf("%s: Have %d, none needed\n", name, count)
    } else {
        var missing []string
        for _, state := range usStates {
            if _, exists := contacts[state]; !exists {
                missing = append(missing, state)
            }
        }
        if len(missing) > 14 {
            fmt.Printf("%s: Have %d, only need %d more\n", name, count, len(missing))
        } else {
            fmt.Printf("%s: Have %d, only need %s\n", name, count, strings.Join(missing, ","))
        }
    }
}

func printQRPProgress(contacts map[string]ProcessedQSO) {
    if len(contacts) == 0 {
        fmt.Println("QRP: Have 0 contacts. Need QRP power (≤5W) logged in ADI file.")
        return
    }

    pts1x := 0.0
    pts2x := 0.0
    count1x := 0
    count2x := 0

    for _, qso := range contacts {
        pts := qrpBandPoints[qso.Band]
        pts1x += pts
        count1x++
        if qso.QRPx2QSO {
            pts2x += pts
            count2x++
        }
    }

    // 1x
    if count1x > 0 {
        level := int(pts1x / 300)
        if level > 0 {
            next := level + 1
            nextTarget := float64(next * 300)
            remaining := nextTarget - pts1x
            plural := "contact"
            if count1x > 1 {
                plural = "contacts"
            }
            fmt.Printf("QRP 1x: Have %d %s, %.1f points which qualifies for 1xQRP x%d. 1xQRP x%d requires %.1f points (%.1f more)\n",
                count1x, plural, pts1x, level, next, nextTarget, remaining)
        } else {
            plural := "contact"
            if count1x > 1 {
                plural = "contacts"
            }
            fmt.Printf("QRP 1x: Have %d %s, %.1f points. 1xQRP x1 requires 300.0 points (%.1f more)\n",
                count1x, plural, pts1x, 300.0-pts1x)
        }
    }

    // 2x
    if count2x > 0 {
        level := int(pts2x / 150)
        if level > 0 {
            next := level + 1
            nextTarget := float64(next * 150)
            remaining := nextTarget - pts2x
            plural := "contact"
            if count2x > 1 {
                plural = "contacts"
            }
            fmt.Printf("QRP 2x: Have %d %s, %.1f points which qualifies for 2xQRP x%d. 2xQRP x%d requires %.1f points (%.1f more)\n",
                count2x, plural, pts2x, level, next, nextTarget, remaining)
        } else {
            plural := "contact"
            if count2x > 1 {
                plural = "contacts"
            }
            fmt.Printf("QRP 2x: Have %d %s, %.1f points. 2xQRP x1 requires 150.0 points (%.1f more)\n",
                count2x, plural, pts2x, 150.0-pts2x)
        }
    }
}

func printDXProgress(dxc, dxq map[string]ProcessedQSO) {
    // DXC
    count := len(dxc)
    if count == 0 {
        fmt.Println("DXC: Have 0 countries. Need DXCC codes in ADI file or member data.")
    } else {
        level, next, target := getDXLevel(count)
        if level == 0 {
            fmt.Printf("DXC: Have %d countries. DXCx%d requires %d (%d more)\n",
                count, next, target, target-count)
        } else {
            fmt.Printf("DXC: Have %d countries which qualifies for DXCx%d. DXCx%d requires %d (%d more)\n",
                count, level, next, target, target-count)
        }
    }

    // DXQ
    count = len(dxq)
    if count == 0 {
        fmt.Println("DXQ: Have 0 foreign member QSOs.")
    } else {
        level, next, target := getDXLevel(count)
        if level == 0 {
            fmt.Printf("DXQ: Have %d foreign member QSOs. DXQx%d requires %d (%d more)\n",
                count, next, target, target-count)
        } else {
            fmt.Printf("DXQ: Have %d foreign member QSOs which qualifies for DXQx%d. DXQx%d requires %d (%d more)\n",
                count, level, next, target, target-count)
        }
    }
}

// calculateAwardLevel calculates award level for awards that increment by 1 up to level 10,
// then by 5 thereafter (C, T, P use variants of this)
func calculateAwardLevel(value int, baseUnit int) int {
	if value < baseUnit {
		return 0 // Not qualified yet
	}

	// Calculate raw level
	rawLevel := value / baseUnit

	if rawLevel <= 10 {
		return rawLevel
	}

	// Beyond level 10, levels increment by 5
	// Calculate how many base units past level 10
	unitsPastThreshold := value - (10 * baseUnit)

	// Each 5 levels worth of base units = one increment
	increments := unitsPastThreshold / (5 * baseUnit)

	// If exactly at a 5-level boundary, use that level
	if unitsPastThreshold%(5*baseUnit) == 0 && unitsPastThreshold > 0 {
		return 10 + (increments * 5)
	}

	// Otherwise, we're at the previous 5-level
	if increments > 0 {
		return 10 + (increments * 5)
	}
	return 10
}

// normalizeDXCC normalizes a DXCC code to 3 digits (zero-padded)
// Examples: "1" -> "001", "291" -> "291"
func normalizeDXCC(code string) string {
	if !isAllDigits(code) {
		return code
	}
	// Pad with leading zeros to make it 3 digits
	for len(code) < 3 {
		code = "0" + code
	}
	return code
}

// formatCTSAwardLevel returns the display string for C/T/S awards in goal/target detection
// If user has no award yet: returns "C", "T", or "S"
// If user has award: returns "Cx40", "Tx45", "Sx10" etc (next multiplier level)
func formatCTSAwardLevel(awardType string, contactCount int, myAwardDate string, baseUnit int) string {
	if effectiveDate(myAwardDate) == "" {
		// User doesn't have this award yet, working toward initial award
		return awardType
	}

	// User has award, working toward next multiplier
	level := calculateAwardLevel(contactCount, baseUnit)

	// Calculate next level
	var nextLevel int
	if level < 10 {
		nextLevel = level + 1
	} else {
		// Round up to next multiple of 5
		nextLevel = ((level / 5) + 1) * 5
	}

	// Format as "Cx40", "Tx45", etc.
	if nextLevel > 1 {
		return fmt.Sprintf("%sx%d", awardType, nextLevel)
	}
	return awardType
}

// formatDXAwardLevel returns the display string for DXC/DXQ awards ("DXCx10", "DXQx400", etc.)
func formatDXAwardLevel(awardType string, currentCount int) string {
	_, nextLevel, _ := getDXLevel(currentCount + 1) // +1 because we're adding one more
	return fmt.Sprintf("%sx%d", awardType, nextLevel)
}

// formatPrefixAwardLevel returns the display string for P awards ("Px20(+14616)", "Px20(new +14616)", etc.)
func formatPrefixAwardLevel(currentPoints int, memberNumber string, existingPrefix *ProcessedQSO) string {
	level := getPrefixLevel(currentPoints)
	var nextLevel int
	if level < 10 {
		nextLevel = level + 1
	} else {
		nextLevel = ((level / 5) + 1) * 5
	}

	memberPoints, _ := strconv.Atoi(memberNumber)

	if existingPrefix != nil {
		// We've worked this prefix before, show point difference
		existingPoints, _ := strconv.Atoi(existingPrefix.PfxPts)
		diff := memberPoints - existingPoints
		return fmt.Sprintf("Px%d(+%d)", nextLevel, diff)
	}
	// New prefix
	return fmt.Sprintf("Px%d(new +%d)", nextLevel, memberPoints)
}

func getPrefixLevel(points int) int {
	// Prefix progression per SKCC rules:
	// Px1-Px10: Each level requires an additional 500,000 points
	// Px1 at >500k, Px2 at >1M, ..., Px10 at >5M
	// Beyond Px10: Px15 at >7.5M, Px20 at >10M, Px25 at >12.5M (2.5M increments)
	if points <= 500000 {
		return 0 // No P award yet
	} else if points <= 5000000 {
		// Px1 through Px10 - each 500k increment adds 1 level
		return points / 500000
	} else {
		// After 5M (Px10): levels jump by 5, thresholds by 2.5M
		// Px10: >5M, Px15: >7.5M, Px20: >10M, Px25: >12.5M
		if points <= 7500000 {
			return 10 // Still at Px10
		} else {
			// Calculate how many 2.5M increments past 7.5M
			incrementsPast7_5M := (points - 7500001) / 2500000 + 1
			return 10 + (int(incrementsPast7_5M) * 5)
		}
	}
}

func getDXLevel(count int) (current, next, target int) {
    if count < 10 {
        return 0, 10, 10
    } else if count < 25 {
        return 10, 25, 25
    } else if count < 50 {
        return 25, 50, 50
    }
    current = 50 + ((count-50)/25)*25
    next = current + 25
    return current, next, next
}

func printRCProgress(contacts map[string]ProcessedQSO) {
    if len(contacts) == 0 {
        fmt.Println("RC: Have 0 qualifying QSOs. Need 30+ minute QSOs with TIME_ON and TIME_OFF logged")
        return
    }

    totalMins := 0
    for _, qso := range contacts {
        totalMins += qso.RagChewMins
    }
    count := len(contacts)

    if totalMins >= 300 {
        level := getRCLevel(totalMins)
        // Calculate next valid level in progression
        var next int
        if level < 10 {
            next = level + 1
        } else {
            // After level 10, progression is by 5s: 15, 20, 25, 30, 35, 40, 45...
            next = ((level / 5) + 1) * 5
        }
        required := getRCRequired(next)
        remaining := required - totalMins
        plural := "QSO"
        if count > 1 {
            plural = "QSOs"
        }
        fmt.Printf("RC: Have %d %s (%s mins) which qualifies for RCx%d. RCx%d requires %s mins (%s more)\n",
            count, plural, formatComma(totalMins), level, next, formatComma(required), formatComma(remaining))
    } else {
        plural := "QSO"
        if count > 1 {
            plural = "QSOs"
        }
        fmt.Printf("RC: Have %d %s (%s mins). RC requires 300 mins (%s more)\n",
            count, plural, formatComma(totalMins), formatComma(300-totalMins))
    }
}

func getRCLevel(mins int) int {
    // RC progression: level = minutes / 300
    // Progression: 1-10 by 1, then 15, 20, 25, 30, 35, 40, 45...
    if mins < 300 {
        return 0
    }
    rawLevel := mins / 300
    if rawLevel <= 10 {
        return rawLevel
    }
    // For levels > 10: increment by 5 for each 5*300 minutes
    unitsPastThreshold := mins - (10 * 300)
    increments := unitsPastThreshold / (5 * 300)
    if unitsPastThreshold%(5*300) == 0 && unitsPastThreshold > 0 {
        return 10 + (increments * 5)
    }
    if increments > 0 {
        return 10 + (increments * 5)
    }
    return 10
}

func getRCRequired(level int) int {
    // RC progression: level = minutes / 300
    // Progression: RC (1), RCx2, RCx3... RCx10, RCx15, RCx20, RCx25...
    if level == 0 {
        return 300
    }
    if level <= 10 {
        return level * 300
    }
    // For levels > 10: progression is 15, 20, 25, 30, 35, 40, 45...
    // Find which progression group this level is in
    // Level 15 = 15*300, Level 20 = 20*300, Level 25 = 25*300, etc.
    return level * 300
}

// ============================================================================
// SPRINT AND WARC BAND CHECKING (for BRAG)
// ============================================================================

// firstWeekdayFromDate returns the first occurrence of the given weekday on or after the given date
func firstWeekdayFromDate(t time.Time, weekday time.Weekday) time.Time {
    for t.Weekday() != weekday {
        t = t.AddDate(0, 0, 1)
    }
    return t
}

// firstWeekdayAfterDate returns the first occurrence of the given weekday strictly after the given date
func firstWeekdayAfterDate(t time.Time, weekday time.Weekday) time.Time {
    t = t.AddDate(0, 0, 1) // Move to next day first
    return firstWeekdayFromDate(t, weekday)
}

// wes calculates Weekend Sprint times (12:00 Saturday to 23:59 Sunday, second full weekend)
func wes(year, month int) (time.Time, time.Time) {
    start := time.Date(year, time.Month(month), 1, 0, 0, 0, 0, time.UTC)
    // First Saturday
    start = firstWeekdayFromDate(start, time.Saturday)
    // Second Saturday
    start = firstWeekdayAfterDate(start, time.Saturday)
    // Add 12 hours for 12:00 start
    start = start.Add(12 * time.Hour)
    // End is 35 hours 59 minutes later (through Sunday 23:59)
    end := start.Add(35*time.Hour + 59*time.Minute)
    return start, end
}

// sks calculates Straight Key Sprint times (4th Wednesday 00:00-02:00 UTC)
func sks(year, month int) (time.Time, time.Time) {
    // SKS: 4th Wednesday 00:00-02:00 UTC
    // Find the 1st Wednesday, then add 3 weeks to get 4th Wednesday
    start := time.Date(year, time.Month(month), 1, 0, 0, 0, 0, time.UTC)
    start = firstWeekdayFromDate(start, time.Wednesday)
    start = start.AddDate(0, 0, 21) // Add 3 weeks
    end := start.Add(2 * time.Hour)
    return start, end
}

// sksa calculates Asia Sprint times (2nd Friday 22:00 to Saturday 00:00 UTC)
func sksa(year, month int) (time.Time, time.Time) {
    start := time.Date(year, time.Month(month), 1, 0, 0, 0, 0, time.UTC)
    // First Friday
    start = firstWeekdayFromDate(start, time.Friday)
    // Second Friday
    start = firstWeekdayAfterDate(start, time.Friday)
    // Add 22 hours for 22:00 start
    start = start.Add(22 * time.Hour)
    // 2 hour duration
    end := start.Add(2 * time.Hour)
    return start, end
}

// skse calculates European Sprint times (1st Thursday)
// Summer (Apr-Oct): 18:45-21:15, Winter: 19:45-22:15 (includes QRS extension)
func skse(year, month int) (time.Time, time.Time) {
    isSummer := month >= 4 && month <= 10
    startHour := 19
    if isSummer {
        startHour = 18
    }

    start := time.Date(year, time.Month(month), 1, 0, 0, 0, 0, time.UTC)
    // Get 1st Thursday
    start = firstWeekdayFromDate(start, time.Thursday)
    // Add start time
    start = start.Add(time.Duration(startHour)*time.Hour + 45*time.Minute)
    // 2.5 hour duration
    end := start.Add(2*time.Hour + 30*time.Minute)
    return start, end
}

// isDuringSprint checks if a given time falls during any SKCC sprint
func isDuringSprint(t time.Time) bool {
    year := t.Year()
    month := int(t.Month())

    // Check all sprint types
    wesStart, wesEnd := wes(year, month)
    sksStart, sksEnd := sks(year, month)
    skseStart, skseEnd := skse(year, month)
    sksaStart, sksaEnd := sksa(year, month)

    sprints := []struct {
        start, end time.Time
    }{
        {start: wesStart, end: wesEnd},
        {start: sksStart, end: sksEnd},
        {start: skseStart, end: skseEnd},
        {start: sksaStart, end: sksaEnd},
    }

    for _, sprint := range sprints {
        if (t.Equal(sprint.start) || t.After(sprint.start)) && (t.Equal(sprint.end) || t.Before(sprint.end)) {
            return true
        }
    }
    return false
}

// isOnWARCFrequency checks if a frequency is on a WARC band (30m, 17m, or 12m)
// WARC bands always count toward BRAG, even during sprints
func isOnWARCFrequency(freqKHz float64) bool {
    // WARC calling frequencies with tolerance
    const tolerance = 10.0

    warcFreqs := []float64{
        10120, // 30m
        18080, // 17m
        24910, // 12m
    }

    for _, freq := range warcFreqs {
        if freqKHz >= freq-tolerance && freqKHz <= freq+tolerance {
            return true
        }
    }
    return false
}

func getBragContactsForMonth(ap *AwardProcessor, year, month int) map[string]bool {
    bragContacts := make(map[string]bool)

    // Get month boundaries
    monthStart := time.Date(year, time.Month(month), 1, 0, 0, 0, 0, time.UTC)
    monthEnd := monthStart.AddDate(0, 1, 0).Add(-time.Second)

    for _, qso := range ap.processedQSOs {
        // Skip K9SKC
        if qso.Call == "K9SKC" {
            continue
        }

        // Skip if no SKCC number
        if qso.SKCCNr == "" || qso.SKCCNr == "NONE" {
            continue
        }

        // Parse QSO date
        qsoTime, err := time.Parse("20060102", qso.QSODate)
        if err != nil {
            continue
        }

        // Check if QSO is within the specified month
        if qsoTime.Before(monthStart) || qsoTime.After(monthEnd) {
            continue
        }

        // Get member info
        member := ap.memberDB[qso.SKCCNr]
        if member == nil {
            continue
        }

        // Check join date
        joinDate := effectiveDate(member.JoinDate)
        if joinDate == "" || qso.QSODate <= joinDate {
            continue
        }

        // BRAG sprint and WARC checking
        // Parse QSO time including hour/minute for sprint checking
        var qsoDateTime time.Time
        if qso.TimeOn != "" {
            // Try to parse full datetime: YYYYMMDDHHMMSS format
            if len(qso.QSODate) >= 8 && len(qso.TimeOn) >= 4 {
                dateTimeStr := qso.QSODate[:8] + qso.TimeOn[:4] + "00"
                var err error
                qsoDateTime, err = time.Parse("20060102150405", dateTimeStr)
                if err != nil {
                    // If parsing fails, use date only (will be treated as no frequency data)
                    qsoDateTime = qsoTime
                }
            } else {
                qsoDateTime = qsoTime
            }
        } else {
            qsoDateTime = qsoTime
        }

        // Check if during sprint
        duringSprint := isDuringSprint(qsoDateTime)

        // Check frequency and WARC band status
        var bragOkay bool
        if qso.Freq != "" {
            // Has frequency data - parse it
            freqMHz, err := strconv.ParseFloat(qso.Freq, 64)
            if err == nil {
                // Convert MHz to kHz
                freqKHz := freqMHz * 1000.0
                onWARCFreq := isOnWARCFrequency(freqKHz)
                bragOkay = onWARCFreq || !duringSprint
            } else {
                // Parse error - treat as no frequency data
                bragOkay = !duringSprint
            }
        } else {
            // No frequency data - only counts if not during sprint
            bragOkay = !duringSprint
        }

        if bragOkay {
            bragContacts[qso.SKCCNr] = true
        }
    }

    return bragContacts
}

func printBRAGProgress(ap *AwardProcessor) {
    // Get current month
    now := time.Now().UTC()
    currentYear := now.Year()
    currentMonth := int(now.Month())

    // Get previous month
    var prevYear, prevMonth int
    if currentMonth == 1 {
        prevYear = currentYear - 1
        prevMonth = 12
    } else {
        prevYear = currentYear
        prevMonth = currentMonth - 1
    }

    // Calculate contacts for both months
    prevMonthContacts := getBragContactsForMonth(ap, prevYear, prevMonth)
    currentMonthContacts := getBragContactsForMonth(ap, currentYear, currentMonth)

    // Month names
    monthNames := []string{"", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"}

    fmt.Printf("BRAG: For %s: %d, For %s: %d\n",
        monthNames[prevMonth], len(prevMonthContacts),
        monthNames[currentMonth], len(currentMonthContacts))
}

func printTKAProgress(sk, bug, ss map[string]ProcessedQSO) {
    allMembers := make(map[string]bool)
    for k := range sk {
        allMembers[k] = true
    }
    for k := range bug {
        allMembers[k] = true
    }
    for k := range ss {
        allMembers[k] = true
    }

    fmt.Printf("TKA: SK:%d/100 BUG:%d/100 SS:%d/100. Unique:%d/300\n",
        len(sk), len(bug), len(ss), len(allMembers))
}

// ============================================================================
// K3Y TRACKING AND DISPLAY
// ============================================================================

// processK3YQSOs processes K3Y QSOs and populates the contactsForK3Y map
func (ap *AwardProcessor) processK3YQSOs(k3yYear int) {
    // K3Y dates: Jan 2 to Feb 1
    k3yStart := fmt.Sprintf("%d010200", k3yYear)
    k3yEnd := fmt.Sprintf("%d020100", k3yYear)

    // K3Y/SKM pattern: matches K3Y or SKM followed by / or - and then the suffix
    k3yPattern := regexp.MustCompile(`(?i)(?:K3Y|SKM)[\/-]([0-9]|KH6|KL7|KP4|AF|AS|EU|NA|OC|SA)`)

    for _, qso := range ap.processedQSOs {
        // Check if QSO is during K3Y period
        qsoDate := qso.QSODate
        if len(qsoDate) < 8 {
            continue
        }
        qsoDatePrefix := qsoDate[:8] + "00" // YYYYMMDD00

        if qsoDatePrefix < k3yStart || qsoDatePrefix >= k3yEnd {
            continue
        }

        // Look for K3Y/SKM in comment
        matches := k3yPattern.FindStringSubmatch(qso.Comment)
        if len(matches) < 2 {
            continue
        }

        suffix := strings.ToUpper(matches[1])

        // Parse frequency to determine band
        if qso.Freq == "" {
            continue
        }

        freqMHz, err := strconv.ParseFloat(qso.Freq, 64)
        if err != nil {
            continue
        }

        freqKHz := freqMHz * 1000.0
        band := whichARRLBand(freqKHz)
        if band == 0 {
            continue
        }

        // Store the contact
        if ap.contactsForK3Y[suffix] == nil {
            ap.contactsForK3Y[suffix] = make(map[int]string)
        }
        ap.contactsForK3Y[suffix][band] = qso.Call
    }
}

// printK3YContacts prints a grid showing K3Y contacts worked
func (ap *AwardProcessor) printK3YContacts(k3yYear int) {
    fmt.Println()
    fmt.Printf("K3Y %d\n", k3yYear)
    fmt.Println("========")

    // Header
    fmt.Printf("%-8s|", "Station")
    bands := []int{160, 80, 40, 30, 20, 17, 15, 12, 10, 6}
    bandNames := []string{"160m", "80m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m"}
    for _, bandName := range bandNames {
        fmt.Printf(" %-7s|", bandName)
    }
    fmt.Println()

    // Helper to print one station row
    printStation := func(stationName, suffix string) {
        fmt.Printf("%-8s|", stationName)
        for _, band := range bands {
            if contacts, exists := ap.contactsForK3Y[suffix]; exists {
                if callsign, worked := contacts[band]; worked {
                    fmt.Printf(" %-7s|", callsign)
                } else {
                    fmt.Printf(" %-7s|", "")
                }
            } else {
                fmt.Printf(" %-7s|", "")
            }
        }
        fmt.Println()
    }

    // Print all stations in order
    printStation("K3Y/0", "0")
    printStation("K3Y/1", "1")
    printStation("K3Y/2", "2")
    printStation("K3Y/3", "3")
    printStation("K3Y/4", "4")
    printStation("K3Y/5", "5")
    printStation("K3Y/6", "6")
    printStation("K3Y/7", "7")
    printStation("K3Y/8", "8")
    printStation("K3Y/9", "9")
    printStation("K3Y/KH6", "KH6")
    printStation("K3Y/KL7", "KL7")
    printStation("K3Y/KP4", "KP4")
    printStation("SKM-AF", "AF")
    printStation("SKM-AS", "AS")
    printStation("SKM-EU", "EU")
    printStation("SKM-NA", "NA")
    printStation("SKM-OC", "OC")
    printStation("SKM-SA", "SA")
}

// ============================================================================
// MAIN
// ============================================================================
//
// NOTE: Real-time monitoring components (RBN connection, Sked monitoring,
// progress dots, file watching) are implemented but not yet integrated into
// the main loop. Current functionality focuses on award calculation from ADI files.

func showUsage(exitCode int) {
    fmt.Println("Usage:")
    fmt.Println()
    fmt.Println("   skcc_skimmer")
    fmt.Println("                   [--adi <adi-file>]")
    fmt.Println("                   [--awards-only]")
    fmt.Println("                   [--bands <comma-separated-bands>]")
    fmt.Println("                   [--brag-months <number-of-months-back>]")
    fmt.Println("                   [--callsign <your-callsign>]")
    fmt.Println("                   [--config-file <full-path-to-config-file>]")
    fmt.Println("                   [--config-path <directory-containing-config>]")
    fmt.Println("                   [--distance-units <mi|km>]")
    fmt.Println("                   [--goals <goals>]")
    fmt.Println("                   [--help]")
    fmt.Println("                   [--interactive]")
    fmt.Println("                   [--logfile <logfile-name>]")
    fmt.Println("                   [--maidenhead <grid-square>]")
    fmt.Println("                   [--notification <on|off>]")
    fmt.Println("                   [--radius <distance-in-miles>]")
    fmt.Println("                   [--sked <on|off>]")
    fmt.Println("                   [--targets <targets>]")
    fmt.Println("                   [--verbose]")
    fmt.Println(" or...")
    fmt.Println()
    fmt.Println("   skcc_skimmer")
    fmt.Println("                   [-a <adi-file>]")
    fmt.Println("                   [-b <comma-separated-bands>]")
    fmt.Println("                   [-c <your-callsign>]")
    fmt.Println("                   [-d <mi|km>]")
    fmt.Println("                   [-f <full-path-to-config-file>]")
    fmt.Println("                   [-g <goals>]")
    fmt.Println("                   [-h]")
    fmt.Println("                   [-i]")
    fmt.Println("                   [-l <logfile-name>]")
    fmt.Println("                   [-m <grid-square>]")
    fmt.Println("                   [-n <on|off>]")
    fmt.Println("                   [-p <directory-containing-config>]")
    fmt.Println("                   [-r <distance-in-miles>]")
    fmt.Println("                   [-s <on|off>]")
    fmt.Println("                   [-t <targets>]")
    fmt.Println("                   [-v]")
    fmt.Println()

    if exitCode == 0 {
        os.Exit(0)
    } else {
        delayedExit(exitCode)
    }
}

// ============================================================================
// MAIN
// ============================================================================

func main() {
    // Parse command-line flags
    callsign := flag.String("c", "", "Your callsign")
    flag.StringVar(callsign, "callsign", "", "Your callsign")
    adiFile := flag.String("a", "", "ADI file path")
    flag.StringVar(adiFile, "adi", "", "ADI file path")
    goals := flag.String("g", "", "Goals (comma-separated)")
    flag.StringVar(goals, "goals", "", "Goals (comma-separated)")
    targets := flag.String("t", "", "Targets (comma-separated)")
    flag.StringVar(targets, "targets", "", "Targets (comma-separated)")
    maidenhead := flag.String("m", "", "Your grid square")
    flag.StringVar(maidenhead, "maidenhead", "", "Your grid square")
    bands := flag.String("b", "", "Comma-separated bands")
    flag.StringVar(bands, "bands", "", "Comma-separated bands")
    radius := flag.Int("r", 0, "Distance in miles")
    flag.IntVar(radius, "radius", 0, "Distance in miles")
    verbose := flag.Bool("v", false, "Verbose output")
    flag.BoolVar(verbose, "verbose", false, "Verbose output")
    logfile := flag.String("l", "", "Logfile name")
    flag.StringVar(logfile, "logfile", "", "Logfile name")
    notification := flag.String("n", "", "Notification (on|off)")
    flag.StringVar(notification, "notification", "", "Notification (on|off)")
    distanceUnits := flag.String("d", "", "Distance units (mi|km)")
    flag.StringVar(distanceUnits, "distance-units", "", "Distance units (mi|km)")
    sked := flag.String("s", "", "Enable sked monitoring (on|off)")
    flag.StringVar(sked, "sked", "", "Enable sked monitoring (on|off)")
    bragMonths := flag.Int("brag-months", 0, "Number of months back for BRAG")
    awardsOnly := flag.Bool("awards-only", false, "Calculate awards only and exit")
    interactive := flag.Bool("i", false, "Interactive mode")
    flag.BoolVar(interactive, "interactive", false, "Interactive mode")
    configFile := flag.String("f", "", "Full path to config file")
    flag.StringVar(configFile, "config-file", "", "Full path to config file")
    configPath := flag.String("p", "", "Directory containing skcc_skimmer.cfg")
    flag.StringVar(configPath, "config-path", "", "Directory containing skcc_skimmer.cfg")
    showHelp := flag.Bool("h", false, "Show help")
    flag.BoolVar(showHelp, "help", false, "Show help")
    flag.Parse()

    // Show help if requested
    if *showHelp {
        showUsage(0)
    }

    fmt.Printf("SKCC Skimmer version %s\n\n", Version)

    // Determine config file path - prefer .toml over .cfg
    var configFilePath string
    if *configFile != "" {
        // User specified explicit file
        configFilePath = *configFile
    } else if *configPath != "" {
        // User specified directory - check for .toml first, then .cfg
        tomlPath := filepath.Join(*configPath, "skcc_skimmer.toml")
        cfgPath := filepath.Join(*configPath, "skcc_skimmer.cfg")
        if _, err := os.Stat(tomlPath); err == nil {
            configFilePath = tomlPath
        } else {
            configFilePath = cfgPath
        }
    } else {
        // Default location - check for .toml first, then .cfg
        if _, err := os.Stat("skcc_skimmer.toml"); err == nil {
            configFilePath = "skcc_skimmer.toml"
        } else {
            configFilePath = "skcc_skimmer.cfg"
        }
    }

    // Get absolute path and directory of config file
    absConfigPath, err := filepath.Abs(configFilePath)
    if err != nil {
        absConfigPath = configFilePath
    }
    configDir := filepath.Dir(absConfigPath)

    // Print which config file is being loaded
    fmt.Printf("Reading configuration from '%s'...\n", absConfigPath)

    // Load configuration
    config, err = parseConfig(configFilePath)
    if err != nil {
        config = &Config{SpottersNearby: make(map[string]bool)}
    }

    // If ADI file from config is relative, make it relative to config file directory
    if config.ADIFile != "" && !filepath.IsAbs(config.ADIFile) {
        config.ADIFile = filepath.Join(configDir, config.ADIFile)
    }

    // Override with command-line flags
    if *callsign != "" {
        config.MyCallsign = strings.ToUpper(*callsign)
    }
    if *adiFile != "" {
        config.ADIFile = *adiFile
    }
    if *goals != "" {
        validGoals := []string{"C", "T", "S", "WAS", "WAS-C", "WAS-T", "WAS-S", "P", "BRAG", "K3Y", "QRP", "DX", "TKA", "RC"}
        config.Goals = parseGoalsTargets(*goals, validGoals, "goal")
    }
    if *targets != "" {
        validTargets := []string{"C", "T", "S"}
        config.Targets = parseGoalsTargets(*targets, validTargets, "target")
    }
    if *maidenhead != "" {
        config.MyGridsquare = strings.ToUpper(*maidenhead)
    }
    if *bands != "" {
        config.Bands = parseBands(*bands)
    }
    if *radius > 0 {
        config.SpotterRadius = *radius
    }
    if *verbose {
        config.Verbose = *verbose
    }
    if *logfile != "" {
        config.LogFile.Enabled = true
        config.LogFile.FileName = *logfile
    }
    if *notification != "" {
        if strings.ToLower(*notification) == "on" {
            config.Notification.Enabled = true
        } else {
            config.Notification.Enabled = false
        }
    }
    if *distanceUnits != "" {
        units := strings.ToLower(*distanceUnits)
        if units == "mi" || units == "km" {
            config.DistanceUnits = units
        }
    }
    if *sked != "" {
        if strings.ToLower(*sked) == "on" {
            config.Sked.Enabled = true
        } else {
            config.Sked.Enabled = false
        }
    }
    // Note: bragMonths not yet implemented in Go version
    _ = bragMonths
    config.AwardsOnly = *awardsOnly
    config.Interactive = *interactive

    // Validate required fields - show usage if missing
    if config.MyCallsign == "" {
        fmt.Println("You must specify your callsign, either on the command line or in 'skcc_skimmer.cfg'.")
        fmt.Println()
        showUsage(1)
    }

    // ADI file is always required
    if config.ADIFile == "" {
        fmt.Println("You must specify an ADI file, either on the command line or in 'skcc_skimmer.cfg'.")
        fmt.Println()
        showUsage(1)
    }

    // For real-time monitoring (not awards-only), maidenhead is required
    if !config.AwardsOnly && config.MyGridsquare == "" {
        fmt.Println("Real-time monitoring requires your grid square. Use --maidenhead or -m to specify it.")
        fmt.Println()
        showUsage(1)
    }

    // Download SKCC data
    if err := downloadSKCCData(); err != nil {
        fmt.Printf("Error downloading SKCC data: %v\n", err)
        delayedExit(1)
    }

    // Check if user is SKCC member
    if members[config.MyCallsign] == nil {
        fmt.Printf("'%s' is not a member of SKCC.\n", config.MyCallsign)
        delayedExit(1)
    }

    // Parse ADI file
    // Download rosters before processing (needed for FYI messages)
    fmt.Println("\nDownloading award rosters...")
    rosters := downloadRosters(config)

    fmt.Printf("\nReading QSOs for %s from '%s'...\n", config.MyCallsign, config.ADIFile)
    qsos, err := parseADI(config.ADIFile)
    if err != nil {
        fmt.Printf("Error reading ADI file: %v\n", err)
        delayedExit(1)
    }

    // Process QSOs through award processor
    ap, err := NewAwardProcessor(members, config.MyCallsign)
    if err != nil {
        fmt.Printf("Error creating award processor: %v\n", err)
        delayedExit(1)
    }

    processedQSOs := ap.ProcessQSOs(qsos)

    // Display processing summary
    if len(ap.qsosSkipped) > 0 {
        qsoWord := "QSO was"
        if len(ap.qsosSkipped) > 1 {
            qsoWord = "QSOs were"
        }
        skippedFile := filepath.Join("QSOs", config.MyCallsign+"-Skipped_QSOs.txt")
        fmt.Printf("\nWARNING: %s %s skipped (non-CW, pre-membership, non-SKCC, etc.)\n",
            formatComma(len(ap.qsosSkipped)), qsoWord)
        fmt.Printf("         See %s for details\n", skippedFile)
    }

    if ap.qsosMissingSKCC > 0 {
        qsoWord := "QSO"
        if ap.qsosMissingSKCC > 1 {
            qsoWord = "QSOs"
        }
        needFile := filepath.Join("QSOs", config.MyCallsign+"-Need_SKCC_Numbers.txt")
        fmt.Printf("\nWARNING: %s %s with SKCC members require SKCC numbers in log to count for awards\n",
            formatComma(ap.qsosMissingSKCC), qsoWord)
        fmt.Printf("         See %s for details\n", needFile)
    }

    if len(ap.qsosAutoMatched) > 0 {
        qsoWord := "QSO is"
        if len(ap.qsosAutoMatched) > 1 {
            qsoWord = "QSOs are"
        }
        inspectFile := filepath.Join("QSOs", config.MyCallsign+"-Inspect_QSOs.txt")
        fmt.Println()
        fmt.Printf("WARNING: %s %s being counted that have no SKCC number in your log.\n",
            formatComma(len(ap.qsosAutoMatched)), qsoWord)
        fmt.Println("         These QSOs were automatically matched to SKCC members in the database.")
        fmt.Println("         If these are POTA, contest, or other non-SKCC QSOs, your award totals may be inflated.")
        fmt.Printf("           (See %s for details.)\n", inspectFile)
        fmt.Println()
        fmt.Println("         Award totals shown include these QSOs (for compatibility with SKCCLogger).")
        fmt.Println()
        fmt.Println("         Please review your log and reconcile these QSOs by either adding the operator's valid ")
        fmt.Println("         SKCC number or specifying NONE in the SKCC field for non-SKCC QSOs.")
    }

    qsoPlural := "QSO"
    if ap.qsosProcessed > 1 {
        qsoPlural = "QSOs"
    }
    qualifyWord := "qualifies"
    if ap.qsosAdded > 1 {
        qualifyWord = "qualify"
    }
    fmt.Printf("\nProcessed %s %s: %s %s for awards\n",
        formatComma(ap.qsosProcessed), qsoPlural, formatComma(ap.qsosAdded), qualifyWord)

    // Dual-pass processing to match Xojo behavior:
    // - C/T/S/DX awards use chronological order (oldest QSO first)
    // - WAS/P/QRP/TKA/BRAG/RC awards use ADI file order

    // Save copy in ADI file order (original order)
    processedQSOsADI := make([]ProcessedQSO, len(processedQSOs))
    copy(processedQSOsADI, processedQSOs)

    // Sort chronologically for C/T/S/DX awards
    processedQSOsChrono := processedQSOs
    sort.Slice(processedQSOsChrono, func(i, j int) bool {
        if processedQSOsChrono[i].QSODate != processedQSOsChrono[j].QSODate {
            return processedQSOsChrono[i].QSODate < processedQSOsChrono[j].QSODate
        }
        return processedQSOsChrono[i].TimeOn < processedQSOsChrono[j].TimeOn
    })

    // Extract awards using dual-pass
    awards := ExtractAwards(processedQSOsChrono, processedQSOsADI)

    // Build QSO index by member number for target calculation
    qsosByMemberNumber := buildQSOsByMemberNumber(processedQSOsChrono)

    // Display configuration summary
    printConfigSummary(config)

    // Print progress
    printProgress(awards, ap)

    // Print FYI messages
    printFYIMessages(awards, rosters, config, members)

    // Process and print K3Y contacts if K3Y is in goals
    if slices.Contains(config.Goals, "K3Y") {
        ap.processK3YQSOs(config.K3YYear)
        ap.printK3YContacts(config.K3YYear)
    }

    // Write award files
    writeAwardFiles(awards, ap)

    if config.AwardsOnly {
        fmt.Println("\nQSO files generated, terminating skcc_skimmer...")
        return
    }

    // Get user's award dates and DXCC code for goal/target display
    myMember := members[config.MyCallsign]
    var myCDate, myTDate, mySDate, myDXCode string
    if myMember != nil {
        myCDate = myMember.CDate
        myTDate = myMember.TDate
        mySDate = myMember.SDate
        myDXCode = myMember.DXCode
    }

    // Create spot processor (used by both interactive and real-time monitoring)
    spotProcessor := NewSpotProcessor(config, members, rosters, awards, qsosByMemberNumber, myCDate, myTDate, mySDate, myDXCode)

    // Handle interactive mode if requested
    if *interactive {
        im := NewInteractiveMode(config, members, rosters, ap, awards, spotProcessor)
        im.Run()
        return
    }

    // Real-time monitoring mode

    // Discover RBN spotters
    spotterMgr := NewSpotterManager()
    if err := spotterMgr.DiscoverSpotters(config.MyGridsquare); err != nil {
        fmt.Printf("*** Error discovering RBN spotters: %v\n", err)
        fmt.Println("Continuing without spotter filtering...")
        config.SpottersNearby = make(map[string]bool)
    } else {
        // Display spotters
        DisplaySpotters(spotterMgr, config.SpotterRadius, config.MyGridsquare, config.DistanceUnits)

        // Populate nearby spotters map
        config.SpottersNearby = make(map[string]bool)
        nearby := spotterMgr.GetNearbySpotters(config.SpotterRadius)
        for _, spotter := range nearby {
            config.SpottersNearby[spotter.Callsign] = true
        }
    }

    // Create context for graceful shutdown
    ctx, cancel := context.WithCancel(context.Background())
    defer cancel()

    // Set up signal handling for Ctrl+C
    sigChan := make(chan os.Signal, 1)
    signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

    // Create WaitGroup for all goroutines
    var wg sync.WaitGroup

    // Display spot windowing configuration
    if config.SpotWindow.Enabled {
        fmt.Printf("\nSpot windowing enabled: aggregating duplicate spots within %d second window\n", config.SpotWindow.Seconds)
    }

    // Clear log file if needed
    if config.LogFile.DeleteOnStartup && config.LogFile.FileName != "" {
        if _, err := os.Stat(config.LogFile.FileName); err == nil {
            os.Remove(config.LogFile.FileName)
        }
    }

    // Launch RBN connection
    rbn := NewRBNConnection(config.MyCallsign)
    wg.Go(func() {
        rbn.ConnectAndProcessTask(ctx, config, spotProcessor)
    })

    // Launch Sked monitoring if enabled
    if config.Sked.Enabled {
        sked := NewSkedMonitor(config, spotProcessor, members, rosters, ap)
        wg.Go(func() {
            sked.MonitorTask(ctx)
        })
    }

    // Launch file watching if ADI file provided
    if config.ADIFile != "" {
        // Create refresh callback that reprocesses awards
        refreshCallback := func() error {
            // Re-read ADI file
            qsos, err := parseADI(config.ADIFile)
            if err != nil {
                return fmt.Errorf("failed to read ADI file: %w", err)
            }

            // Process QSOs
            processedQSOs := ap.ProcessQSOs(qsos)

            // Sort chronologically
            processedQSOsChrono := make([]ProcessedQSO, len(processedQSOs))
            copy(processedQSOsChrono, processedQSOs)
            sort.Slice(processedQSOsChrono, func(i, j int) bool {
                if processedQSOsChrono[i].QSODate != processedQSOsChrono[j].QSODate {
                    return processedQSOsChrono[i].QSODate < processedQSOsChrono[j].QSODate
                }
                return processedQSOsChrono[i].TimeOn < processedQSOsChrono[j].TimeOn
            })

            // ADI order copy
            processedQSOsADI := make([]ProcessedQSO, len(processedQSOs))
            copy(processedQSOsADI, processedQSOs)

            // Extract awards
            newAwards := ExtractAwards(processedQSOsChrono, processedQSOsADI)

            // Build QSO index
            newQSOsByMemberNumber := buildQSOsByMemberNumber(processedQSOsChrono)

            // Update spot processor (thread-safe)
            spotProcessor.mu.Lock()
            spotProcessor.awards = newAwards
            spotProcessor.qsosByMemberNumber = newQSOsByMemberNumber
            spotProcessor.mu.Unlock()

            // Display updated progress and FYI messages
            printProgress(newAwards, ap)
            fmt.Println()
            printFYIMessages(newAwards, rosters, config, members)

            return nil
        }

        fw := NewFileWatcher(config, config.ADIFile, refreshCallback)
        wg.Go(func() {
            fw.WatchTask(ctx)
        })
    }

    // Launch progress dots if enabled (but not in verbose mode)
    if config.ProgressDots.Enabled && !config.Verbose {
        wg.Go(func() {
            runProgressDotsTask(ctx, config)
        })
    }

    // Handle Ctrl+C - exit immediately (OS will clean up)
    go func() {
        <-sigChan
        os.Exit(0)
    }()

    // Keep main goroutine alive
    wg.Wait()
}

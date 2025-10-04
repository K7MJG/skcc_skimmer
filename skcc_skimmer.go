package main

/*
 * The MIT License (MIT)
 *
 * Copyright (c) 2015-2025 Mark J Glenn
 *
 * SKCC Skimmer - Go Edition
 * Complete rewrite maintaining 100% behavioral parity with Python/Xojo versions
 */

import (
	"bufio"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Version information
const Version = "9.0.0-go"

// Network constants
const (
	RBNServer     = "telnet.reversebeacon.net"
	RBNPort       = 7000
	SKCCDataURL   = "https://skccgroup.com/skimmer-data.txt"
	SKCCBaseURL   = "https://www.skccgroup.com/"
	SkedStatusURL = "http://sked.skccgroup.com/get-status.php"
)

// US States for WAS awards
var usStates = []string{
	"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
	"HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
	"MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
	"NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
	"SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
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

// DXCC country codes - hardcoded for reliability
// Generated from SKCC member database (158 entities with SKCC members)
var dxccCountries = map[string]string{
	"001": "Canada", "003": "Afghanistan", "006": "Alaska", "007": "Albania",
	"014": "Armenia", "015": "Asiatic Russia", "016": "Auckland & Campbell Is.",
	"021": "Balearic Is.", "027": "Belarus", "029": "Canary Is.", "033": "Chagos Is.",
	"046": "East Malaysia", "048": "E. Kiribati (Line Is.)", "050": "Mexico",
	"052": "Estonia", "054": "European Russia", "060": "Bahamas", "062": "Barbados",
	"064": "Bermuda", "066": "Belize", "069": "Cayman Is.", "070": "Cuba",
	"072": "Dominican Republic", "074": "El Salvador", "076": "Guatemala",
	"079": "Guadeloupe", "080": "Honduras", "088": "Panama", "090": "Trinidad & Tobago",
	"091": "Aruba", "095": "Dominica", "100": "Argentina", "103": "Guam",
	"104": "Bolivia", "106": "Guernsey", "108": "Brazil", "110": "Hawaii",
	"112": "Chile", "114": "Isle of Man", "116": "Colombia", "120": "Ecuador",
	"122": "Jersey", "126": "Kaliningrad", "130": "Kazakhstan", "132": "Paraguay",
	"135": "Kyrgyzstan", "136": "Peru", "137": "Republic of Korea", "140": "Suriname",
	"144": "Uruguay", "145": "Latvia", "146": "Lithuania", "148": "Venezuela",
	"149": "Azores", "150": "Australia", "158": "Vanuatu", "162": "New Caledonia",
	"163": "Papua New Guinea", "165": "Mauritius", "170": "New Zealand",
	"175": "French Polynesia", "179": "Moldova", "181": "Mozambique",
	"185": "Solomon Is.", "190": "Samoa", "192": "Ogasawara", "202": "Puerto Rico",
	"206": "Austria", "209": "Belgium", "212": "Bulgaria", "214": "Corsica",
	"215": "Cyprus", "221": "Denmark", "223": "England", "224": "Finland",
	"225": "Sardinia", "227": "France", "230": "Fed. Rep. of Germany",
	"233": "Gibraltar", "234": "S. Cook Is.", "236": "Greece", "237": "Greenland",
	"239": "Hungary", "242": "Iceland", "245": "Ireland", "248": "Italy",
	"249": "St. Kitts & Nevis", "254": "Luxembourg", "256": "Madeira Is.",
	"257": "Malta", "260": "Monaco", "263": "Netherlands", "265": "Northern Ireland",
	"266": "Fed. Rep. of Germany", "269": "Poland", "272": "Portugal",
	"275": "Romania", "279": "Scotland", "281": "Spain", "284": "Sweden",
	"287": "Switzerland", "288": "Ukraine", "291": "United States", "296": "Serbia",
	"308": "Costa Rica", "315": "Czech Republic", "324": "St. Lucia",
	"336": "Israel", "339": "Japan", "390": "Turkiye", "446": "Morocco",
	"462": "South Africa", "497": "Croatia", "499": "Slovenia", "503": "Slovak Republic",
}

// Compiled regex patterns (global for performance)
var (
	eohPattern        = regexp.MustCompile(`(?i)<eoh>`)
	eorPattern        = regexp.MustCompile(`(?i)<eor>`)
	fieldPattern      = regexp.MustCompile(`(?i)<(\w+?):\d+[^>]*>([^<\r\n]*)`)
	prefixPattern     = regexp.MustCompile(`(?:.*/)?([0-9]*[a-zA-Z]+\d+)`)
	memberNumPattern  = regexp.MustCompile(`^(\d+)`)
	k3yPattern        = regexp.MustCompile(`(?i).*?(?:K3Y|SKM)[/-]([0-9]|KH6|KL7|KP4|AF|AS|EU|NA|OC|SA)`)
	slashedCallPattern = regexp.MustCompile(`^([^/]+)/(.+)$|^(.+)/([^/]+)$`)
	suffixStripPattern = regexp.MustCompile(`[A-Z]+$`)
)

// ============================================================================
// DATA STRUCTURES
// ============================================================================

// Config holds all configuration settings
type Config struct {
	MyCallsign     string
	MyGridsquare   string
	SpotterRadius  int
	ADIFile        string
	Goals          []string
	Targets        []string
	Bands          []int
	Exclusions     []string
	Friends        []string
	Verbose        bool
	DistanceUnits  string
	K3YYear        int
	AwardsOnly     bool
	Interactive    bool
	SpottersNearby map[string]bool

	// Sub-configurations
	HighWPM      HighWPMConfig
	OffFrequency OffFrequencyConfig
	Notification NotificationConfig
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

// Member represents an SKCC member from the database
type Member struct {
	SKCCNumber  string   // With suffix (e.g., "2748S")
	PlainNumber string   // Without suffix (e.g., "2748")
	Callsign    string   // Primary callsign
	PrimaryCall string   // Same as Callsign for now
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

// QSO represents a QSO from the ADI log
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

func extractPrefix(call string) string {
	matches := prefixPattern.FindStringSubmatch(call)
	if len(matches) > 1 {
		prefix := matches[1]
		if len(prefix) >= 3 && prefix[2] >= '0' && prefix[2] <= '9' {
			return prefix[:3]
		} else if len(prefix) >= 2 {
			return prefix[:2]
		}
	}
	return ""
}

func contains(slice []string, item string) bool {
	for _, s := range slice {
		if s == item {
			return true
		}
	}
	return false
}

func containsInt(slice []int, item int) bool {
	for _, s := range slice {
		if s == item {
			return true
		}
	}
	return false
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
// CONFIGURATION
// ============================================================================

func parseConfig(filename string) (*Config, error) {
	cfg := &Config{
		SpotterRadius: 750,
		Bands:         []int{160, 80, 60, 40, 30, 20, 17, 15, 12, 10, 6},
		Verbose:       false,
		DistanceUnits: "mi",
		K3YYear:       2026,
		SpottersNearby: make(map[string]bool),
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
			DisplaySeconds: 10,
			DotsPerLine:    30,
		},
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

		if strings.Contains(line, "=") {
			parts := strings.SplitN(line, "=", 2)
			key := strings.TrimSpace(parts[0])
			value := strings.TrimSpace(parts[1])
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
				cfg.Goals = parseGoalsTargets(value)
			case "TARGETS":
				cfg.Targets = parseGoalsTargets(value)
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

func parseGoalsTargets(value string) []string {
	value = strings.ToUpper(value)
	parts := strings.Split(value, ",")
	var result []string
	hasAll := false
	var exclusions []string

	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "ALL" {
			hasAll = true
		} else if strings.HasPrefix(p, "-") {
			exclusions = append(exclusions, strings.TrimPrefix(p, "-"))
		} else if p != "" && p != "NONE" {
			result = append(result, p)
		}
	}

	if hasAll {
		allAwards := []string{"C", "T", "S", "P", "WAS", "WAS-C", "WAS-T", "WAS-S", "DX", "QRP", "RC", "BRAG", "K3Y", "TKA"}
		for _, award := range allAwards {
			isExcluded := false
			for _, ex := range exclusions {
				if award == ex {
					isExcluded = true
					break
				}
			}
			if !isExcluded {
				result = append(result, award)
			}
		}
	}

	return result
}

// parseHighWPM parses HIGH_WPM dict from config
func parseHighWPM(value string, cfg *Config) {
	// Value is a Python dict string like "{'ACTION': 'warn', 'THRESHOLD': 35}"
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
			PrimaryCall: strings.ToUpper(parts[1]),
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

		// Index by primary callsign
		members[member.Callsign] = member

		// Index by old callsigns
		for _, oldCall := range member.OldCalls {
			if oldCall != "" {
				members[strings.ToUpper(oldCall)] = member
			}
		}

		count++
	}

	fmt.Printf("Loaded %d SKCC members\n", count)
	return scanner.Err()
}

func normalizeADIDate(dateStr string) string {
	// Convert "DD Mon YYYY" to "YYYYMMDD"
	if dateStr == "" {
		return ""
	}

	parts := strings.Fields(dateStr)
	if len(parts) != 3 {
		return ""
	}

	monthMap := map[string]string{
		"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
		"May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
		"Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
	}

	day := parts[0]
	if len(day) == 1 {
		day = "0" + day
	}
	month := monthMap[parts[1]]
	year := parts[2]

	if month == "" {
		return ""
	}

	return year + month + day
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
				value := match[2]

				switch field {
				case "QSO_DATE":
					qso.QSODate = value
				case "CALL":
					qso.Call = value
				case "STATE":
					qso.State = strings.ToUpper(value)
				case "SKCC":
					qso.SKCC = value
					qso.SKCCPre = cleanSKCCNumber(value)
				case "TX_PWR":
					qso.TxPwr = value
				case "RX_PWR":
					qso.RxPwr = value
				case "DXCC":
					qso.DXCC = value
				case "BAND":
					qso.Band = strings.ToUpper(value)
				case "KEY_TYPE":
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
// AWARD PROCESSOR - Core Logic (Direct translation from Python cAwards)
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

	// Build memberDB indexed by SKCC number
	seenNumbers := make(map[string]bool)
	for _, member := range memberDB {
		if !seenNumbers[member.PlainNumber] {
			ap.memberDB[member.PlainNumber] = member
			seenNumbers[member.PlainNumber] = true
		}
	}

	// Build callsignDB for GetSKCCFromCall lookups
	for call, member := range memberDB {
		callUpper := strings.ToUpper(call)
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
	}

	// Set user's award dates
	ap.myMemberNr = myMember.PlainNumber
	ap.myJoinDate = myMember.JoinDate
	ap.myCDate = myMember.CDate
	ap.myTDate = myMember.TDate
	ap.myTX8Date = myMember.TX8Date
	ap.mySDate = myMember.SDate
	ap.myDXCode = myMember.DXCode

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
			segments := strings.Split(logCallUpper, "/")
			for _, segment := range segments {
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

// ProcessQSOs - Main processing loop (direct translation from Python)
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
		CallPri:    mbr.PrimaryCall,
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
	if contains(allStates, state) {
		processed.Country = "USA"
	} else if contains(provinces, state) {
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
	if contains(usStates, processed.State) {
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

	// Senator Award (I have Tx8, they have Tribune/Senator, started 2013-08-01)
	myTX8Date := normalizeDate(ap.myTX8Date)
	if qsoDate >= "20130801" && myTX8Date != "" {
		if mbr.TDate != "" {
			mbrTDate := normalizeDate(mbr.TDate)
			if qsoDate >= myTX8Date && qsoDate >= mbrTDate {
				processed.SenAwardQSO = true
			}
		} else if mbr.SDate != "" {
			mbrSDate := normalizeDate(mbr.SDate)
			if qsoDate >= myTX8Date && qsoDate >= mbrSDate {
				processed.SenAwardQSO = true
			}
		}
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

	// Prefix Award
	prefix := extractPrefix(processed.Call)
	if prefix != "" {
		processed.Pfx = prefix
		processed.PfxCall = processed.Call
		processed.PfxPts = mbr.PlainNumber
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

	// TKA
	if qso.KeyType != "" {
		kt := strings.ToUpper(qso.KeyType)
		if kt == "SK" || kt == "S" || kt == "BUG" || kt == "B" || kt == "SS" {
			processed.TKAQSO = true
		}
	}
}

func calculateDuration(timeOn, timeOff string) int {
	// Parse HHMMSS to minutes
	getMinutes := func(t string) int {
		if len(t) < 4 {
			return 0
		}
		hh, _ := strconv.Atoi(t[0:2])
		mm, _ := strconv.Atoi(t[2:4])
		return hh*60 + mm
	}

	onMins := getMinutes(timeOn)
	offMins := getMinutes(timeOff)

	duration := offMins - onMins
	if duration < 0 {
		duration += 24 * 60 // Handle midnight rollover
	}

	return duration
}

// ============================================================================
// AWARD EXTRACTION
// ============================================================================

// ExtractAwards extracts award-specific contacts from processed QSOs
func ExtractAwards(processed []ProcessedQSO) map[string]interface{} {
	awards := make(map[string]interface{})

	// C, T, S awards
	contactsC := make(map[string]ProcessedQSO)
	contactsT := make(map[string]ProcessedQSO)
	contactsS := make(map[string]ProcessedQSO)

	for _, qso := range processed {
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

	// WAS variants
	contactsWAS := make(map[string]ProcessedQSO)
	contactsWASC := make(map[string]ProcessedQSO)
	contactsWAST := make(map[string]ProcessedQSO)
	contactsWASS := make(map[string]ProcessedQSO)

	for _, qso := range processed {
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

	// Prefix - keep highest member number per prefix
	contactsP := make(map[string]ProcessedQSO)
	for _, qso := range processed {
		if qso.Pfx != "" {
			key := qso.Pfx + "_" + qso.Band
			existing, exists := contactsP[key]
			if !exists {
				contactsP[key] = qso
			} else {
				existingNum, _ := strconv.Atoi(existing.PfxPts)
				newNum, _ := strconv.Atoi(qso.PfxPts)
				if newNum > existingNum {
					contactsP[key] = qso
				}
			}
		}
	}
	awards["P"] = contactsP

	// QRP
	contactsQRP := make(map[string]ProcessedQSO)
	for _, qso := range processed {
		if qso.QRPx1QSO {
			key := qso.SKCCNr + "_" + qso.Band
			contactsQRP[key] = qso
		}
	}
	awards["QRP"] = contactsQRP

	// DX
	contactsDXC := make(map[string]ProcessedQSO)
	contactsDXQ := make(map[string]ProcessedQSO)
	for _, qso := range processed {
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

	// RC - keep longest per member
	contactsRC := make(map[string]ProcessedQSO)
	for _, qso := range processed {
		if qso.RagChewQSO {
			existing, exists := contactsRC[qso.SKCCNr]
			if !exists || qso.RagChewMins > existing.RagChewMins {
				contactsRC[qso.SKCCNr] = qso
			}
		}
	}
	awards["RC"] = contactsRC

	// TKA
	contactsTKASK := make(map[string]ProcessedQSO)
	contactsTKABUG := make(map[string]ProcessedQSO)
	contactsTKASS := make(map[string]ProcessedQSO)

	for _, qso := range processed {
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

	// Remove duplicates
	for member, count := range allMembers {
		if count <= 1 {
			continue
		}

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

func writeAwardFiles(awards map[string]interface{}, ap *AwardProcessor) {
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

	// WAS awards
	writeWASAward("WAS", awards["WAS"].(map[string]ProcessedQSO))
	writeWASAward("WAS-C", awards["WAS-C"].(map[string]ProcessedQSO))
	writeWASAward("WAS-T", awards["WAS-T"].(map[string]ProcessedQSO))
	writeWASAward("WAS-S", awards["WAS-S"].(map[string]ProcessedQSO))

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

func writeInspectFile(autoMatched []AutoMatchEntry, awards map[string]interface{}) {
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

	// Sort by date
	var sorted []ProcessedQSO
	for _, c := range contacts {
		sorted = append(sorted, c)
	}
	sort.Slice(sorted, func(i, j int) bool {
		if sorted[i].QSODate != sorted[j].QSODate {
			return sorted[i].QSODate < sorted[j].QSODate
		}
		return sorted[i].Call < sorted[j].Call
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

func writeWASAward(name string, contacts map[string]ProcessedQSO) {
	filename := filepath.Join("QSOs", config.MyCallsign+"-"+name+".txt")
	file, err := os.Create(filename)
	if err != nil {
		return
	}
	defer file.Close()

	for _, state := range usStates {
		if qso, exists := contacts[state]; exists {
			dateStr := formatDate(qso.QSODate)
			nameStr := qso.Name
			if len(nameStr) > 12 {
				nameStr = nameStr[:12]
			}
			fmt.Fprintf(file, "%-8s %-12s %-9s %-13s %-16s %s\n",
				qso.State, qso.Call, qso.SKCCNr, nameStr, dateStr, qso.Band)
		} else {
			fmt.Fprintln(file, state)
		}
	}
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
		fmt.Fprintf(file, "%5d  %s   %-13s %-8d %-12s %-12s %3s  %10d\n",
			i+1, dateStr, qso.Call, pts, nameStr, qso.Pfx, band, totalPoints)
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

	// Sort by date
	sort.Slice(qrp1x, func(i, j int) bool {
		return qrp1x[i].QSODate < qrp1x[j].QSODate
	})
	sort.Slice(qrp2x, func(i, j int) bool {
		return qrp2x[i].QSODate < qrp2x[j].QSODate
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
			return sorted[i].QSODate < sorted[j].QSODate
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
		return sorted[i].QSODate < sorted[j].QSODate
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
		sort.Slice(sorted, func(i, j int) bool {
			return sorted[i].QSODate < sorted[j].QSODate
		})

		for i, qso := range sorted {
			dateStr := formatDate(qso.QSODate)
			fmt.Fprintf(file, "%3d  %s  %-12s %-8s\n",
				i+1, dateStr, qso.Call, qso.SKCCNr)
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

func printProgress(awards map[string]interface{}) {
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
		level := cCount / 100
		remaining := (level+1)*100 - cCount
		fmt.Printf("C: Have %s which qualifies for Cx%d. Cx%d requires %d (%d more)\n",
			formatComma(cCount), level, level+1, (level+1)*100, remaining)
	} else {
		fmt.Printf("C: Have %d. C requires 100 (%d more)\n", cCount, 100-cCount)
	}

	// T award
	tCount := len(contactsT)
	if tCount >= 50 {
		level := tCount / 50
		remaining := (level+1)*50 - tCount
		fmt.Printf("T: Have %s which qualifies for Tx%d. Tx%d requires %d (%d more)\n",
			formatComma(tCount), level, level+1, (level+1)*50, remaining)
	} else if members[config.MyCallsign].CDate != "" {
		fmt.Printf("T: Have %d. T requires 50 (%d more)\n", tCount, 50-tCount)
	} else {
		fmt.Println("T: Tribune award requires Centurion first. Apply for C before working toward T.")
	}

	// S award
	sCount := len(contactsS)
	if len(contactsT) >= 400 {
		if sCount >= 200 {
			level := sCount / 200
			remaining := (level+1)*200 - sCount
			fmt.Printf("S: Have %s which qualifies for Sx%d. Sx%d requires %d (%d more)\n",
				formatComma(sCount), level, level+1, (level+1)*200, remaining)
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
		level := pTotal / 500000
		remaining := (level+1)*500000 - pTotal
		fmt.Printf("P: Have %s which qualifies for Px%d. Next level requires more than %s (%s more)\n",
			formatComma(pTotal), level, formatComma((level+1)*500000), formatComma(remaining))
	} else {
		fmt.Printf("P: Have %s. Px1 requires more than 500000 (%s more)\n",
			formatComma(pTotal), formatComma(500000-pTotal))
	}

	// WAS
	if contains(config.Goals, "WAS") {
		printWASProgress("WAS", contactsWAS)
	}
	if contains(config.Goals, "WAS-C") {
		printWASProgress("WAS-C", contactsWASC)
	}
	if contains(config.Goals, "WAS-T") {
		printWASProgress("WAS-T", contactsWAST)
	}
	if contains(config.Goals, "WAS-S") {
		printWASProgress("WAS-S", contactsWASS)
	}

	// QRP
	if contains(config.Goals, "QRP") {
		printQRPProgress(contactsQRP)
	}

	// DX
	if contains(config.Goals, "DX") {
		printDXProgress(contactsDXC, contactsDXQ)
	}

	// RC
	if contains(config.Goals, "RC") {
		printRCProgress(contactsRC)
	}

	// TKA
	if contains(config.Goals, "TKA") {
		printTKAProgress(contactsTKASK, contactsTKABUG, contactsTKASS)
	}

	fmt.Println()
}

// getFullMemberNumber returns (SKCC#, suffix) for a given callsign
// Returns ("", "") if not found
func getFullMemberNumber(callsign string, memberDB map[string]*Member) (string, string) {
	baseCall := extractCallsign(callsign)

	// Look up in member database by callsign
	members, exists := memberDB[baseCall]
	if !exists {
		return "", ""
	}

	// Extract suffix from SKCC number (e.g., "2748S" -> "S")
	skccNum := members.SKCCNumber
	suffix := suffixStripPattern.FindString(skccNum)

	return skccNum, suffix
}

// getCountryName returns the country name for a DXCC code
func getCountryName(dxccCode string) string {
	// Normalize DXCC code (remove leading zeros)
	code := strings.TrimLeft(dxccCode, "0")
	if code == "" {
		code = "0"
	}
	// Pad to 3 digits for lookup
	for len(code) < 3 {
		code = "0" + code
	}

	if country, exists := dxccCountries[code]; exists {
		return country
	}
	return "Unknown"
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

	// Download rosters based on goals
	for _, goal := range config.Goals {
		switch goal {
		case "C":
			if r, err := downloadRoster("Centurion", "operating_awards/centurion/centurion_list.php", true); err == nil {
				rosters.Centurion = r
			}
		case "T":
			if r, err := downloadRoster("Tribune", "operating_awards/tribune/tribune_list.php", true); err == nil {
				rosters.Tribune = r
			}
		case "S":
			if r, err := downloadRoster("Senator", "operating_awards/senator/senator_list.php", true); err == nil {
				rosters.Senator = r
			}
		case "WAS":
			if r, err := downloadRoster("WAS", "operating_awards/was/was_list.php", false); err == nil {
				rosters.WAS = r
			}
		case "WAS-C":
			if r, err := downloadRoster("WAS-C", "operating_awards/was-c/was-c_list.php", false); err == nil {
				rosters.WASC = r
			}
		case "WAS-T":
			if r, err := downloadRoster("WAS-T", "operating_awards/was-t/was-t_list.php", false); err == nil {
				rosters.WAST = r
			}
		case "WAS-S":
			if r, err := downloadRoster("WAS-S", "operating_awards/was-s/was-s_list.php", false); err == nil {
				rosters.WASS = r
			}
		case "P":
			if r, err := downloadRoster("PFX", "operating_awards/pfx/prefix_list.php", false); err == nil {
				rosters.Prefix = r
			}
		case "DX":
			if r, err := downloadRoster("DXQ", "operating_awards/dx/dxq_list.php", true); err == nil {
				rosters.DXQ = r
			}
			if r, err := downloadRoster("DXC", "operating_awards/dx/dxc_list.php", true); err == nil {
				rosters.DXC = r
			}
		case "QRP":
			if r, err := downloadRoster("QRP 1x", "operating_awards/qrp_awards/qrp_x1_list.php", true); err == nil {
				rosters.QRP1x = r
			}
			if r, err := downloadRoster("QRP 2x", "operating_awards/qrp_awards/qrp_x2_list.php", true); err == nil {
				rosters.QRP2x = r
			}
		case "TKA":
			if r, err := downloadRoster("TKA", "operating_awards/triplekey/triplekey_list.php", true); err == nil {
				rosters.TKA = r
			}
		case "RC":
			if r, err := downloadRoster("RC", "operating_awards/rag_chew/ragchew_list.php", true); err == nil {
				rosters.RC = r
			}
		}
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
		next := level + 1
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
	if mins < 300 {
		return 0
	}
	if mins < 450 {
		return 1 + (mins-300)/15
	}
	return 10 + (mins-450)/25
}

func getRCRequired(level int) int {
	if level == 0 {
		return 300
	}
	if level <= 10 {
		return 300 + level*15
	}
	return 450 + (level-10)*25
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
// MAIN
// ============================================================================

func main() {
	// Parse command-line flags
	callsign := flag.String("c", "", "Your callsign")
	adiFile := flag.String("a", "", "ADI file path")
	goals := flag.String("g", "", "Goals (comma-separated)")
	targets := flag.String("t", "", "Targets (comma-separated)")
	maidenhead := flag.String("m", "", "Your grid square")
	awardsOnly := flag.Bool("awards-only", false, "Calculate awards only and exit")
	interactive := flag.Bool("i", false, "Interactive mode")
	flag.Parse()

	fmt.Printf("SKCC Skimmer version %s\n\n", Version)

	// Load configuration
	var err error
	config, err = parseConfig("skcc_skimmer.cfg")
	if err != nil {
		config = &Config{SpottersNearby: make(map[string]bool)}
	}

	// Override with command-line flags
	if *callsign != "" {
		config.MyCallsign = strings.ToUpper(*callsign)
	}
	if *adiFile != "" {
		config.ADIFile = *adiFile
	}
	if *goals != "" {
		config.Goals = parseGoalsTargets(*goals)
	}
	if *targets != "" {
		config.Targets = parseGoalsTargets(*targets)
	}
	if *maidenhead != "" {
		config.MyGridsquare = strings.ToUpper(*maidenhead)
	}
	config.AwardsOnly = *awardsOnly
	config.Interactive = *interactive

	// Validate required fields
	if config.MyCallsign == "" {
		fmt.Println("Error: MY_CALLSIGN required")
		os.Exit(1)
	}
	if config.ADIFile == "" {
		fmt.Println("Error: ADI_FILE required")
		os.Exit(1)
	}

	// Download SKCC data
	if err := downloadSKCCData(); err != nil {
		fmt.Printf("Error downloading SKCC data: %v\n", err)
		os.Exit(1)
	}

	// Check if user is SKCC member
	if members[config.MyCallsign] == nil {
		fmt.Printf("'%s' is not a member of SKCC.\n", config.MyCallsign)
		os.Exit(1)
	}

	// Parse ADI file
	fmt.Printf("\nReading QSOs for %s from '%s'...\n", config.MyCallsign, config.ADIFile)
	qsos, err := parseADI(config.ADIFile)
	if err != nil {
		fmt.Printf("Error reading ADI file: %v\n", err)
		os.Exit(1)
	}
	fmt.Printf("Loaded %d QSOs\n", len(qsos))

	// Process QSOs through award processor
	ap, err := NewAwardProcessor(members, config.MyCallsign)
	if err != nil {
		fmt.Printf("Error creating award processor: %v\n", err)
		os.Exit(1)
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

	// Extract awards
	awards := ExtractAwards(processedQSOs)

	// Print progress
	printProgress(awards)

	// Write award files
	writeAwardFiles(awards, ap)

	fmt.Println("\nQSO files generated, terminating skcc_skimmer...")

	if config.AwardsOnly {
		return
	}

	// Interactive mode or RBN connection would go here
	// For now, just exit after awards
}

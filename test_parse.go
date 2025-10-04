package main

import (
	"fmt"
	"io"
	"os"
	"regexp"
	"strings"
)

func main() {
	file, _ := os.Open("../ADI/AC2C.adi")
	defer file.Close()
	
	content, _ := io.ReadAll(file)
	text := string(content)
	
	eohPattern := regexp.MustCompile(`(?i)<eoh>`)
	eorPattern := regexp.MustCompile(`(?i)<eor>`)
	fieldPattern := regexp.MustCompile(`(?i)<(\w+?):\d+[^>]*>([^<]*)`)
	
	// Find end of header
	eohIdx := eohPattern.FindStringIndex(text)
	if eohIdx != nil {
		text = text[eohIdx[1]:]
	}
	
	// Split by <eor>
	records := eorPattern.Split(text, -1)
	
	fmt.Printf("Total records: %d\n", len(records))
	
	cwCount := 0
	for i, record := range records {
		if i >= 3 { break } // Just first 3
		if strings.TrimSpace(record) == "" {
			continue
		}
		
		isCW := false
		call := ""
		matches := fieldPattern.FindAllStringSubmatch(record, -1)
		
		for _, match := range matches {
			if len(match) >= 3 {
				field := strings.ToUpper(match[1])
				value := match[2]
				
				if field == "MODE" {
					if strings.ToUpper(value) == "CW" {
						isCW = true
					}
				}
				if field == "CALL" {
					call = value
				}
			}
		}
		
		if isCW {
			cwCount++
			fmt.Printf("Record %d: %s (CW)\n", i, call)
		}
	}
	fmt.Printf("Total CW QSOs: %d\n", cwCount)
}

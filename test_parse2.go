package main

import (
	"fmt"
	"io"
	"os"
	"regexp"
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
	
	// Print first record
	fmt.Println("First record:")
	fmt.Println(records[1]) // Skip empty first
	fmt.Println("\n---\nMatches:")
	matches := fieldPattern.FindAllStringSubmatch(records[1], -1)
	for _, match := range matches {
		if len(match) >= 3 {
			fmt.Printf("%s = %s\n", match[1], match[2])
		}
	}
}

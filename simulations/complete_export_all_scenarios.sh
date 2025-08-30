#!/bin/bash
# Test all export types for one scenario

SCENARIO="${1:-scenario-01-baseline-01_fixed_baseline-s0}"
RESULTS_DIR="/d/Doctorat/anul_2/apps/FLoRa_development/flora/simulations/results"
OUTPUT_DIR="/d/Doctorat/anul_2/apps/FLoRa_development/flora/simulations/json_exports"

mkdir -p "$OUTPUT_DIR"

echo "Testing All Export Types for: $SCENARIO"
echo "======================================="

# Check what data is available
echo "Available data in .sca file:"
opp_scavetool query "$RESULTS_DIR/${SCENARIO}.sca"
echo ""

if [ -f "$RESULTS_DIR/${SCENARIO}.sca" ]; then
    
    echo "1. Exporting scalars..."
    if opp_scavetool export -f JSON -o "$OUTPUT_DIR/test_scalars.json" -f 'type =~ scalar' "$RESULTS_DIR/${SCENARIO}.sca"; then
        SIZE=$(ls -lh "$OUTPUT_DIR/test_scalars.json" | awk '{print $5}')
        echo "   SUCCESS: test_scalars.json ($SIZE)"
    else
        echo "   FAILED"
    fi
    
    echo "2. Exporting parameters..."
    if opp_scavetool export -f JSON -o "$OUTPUT_DIR/test_parameters.json" -f 'type =~ parameter' "$RESULTS_DIR/${SCENARIO}.sca"; then
        SIZE=$(ls -lh "$OUTPUT_DIR/test_parameters.json" | awk '{print $5}')
        echo "   SUCCESS: test_parameters.json ($SIZE)"
    else
        echo "   FAILED"
    fi
    
    echo "3. Exporting histograms..."
    if opp_scavetool export -f JSON -o "$OUTPUT_DIR/test_histograms.json" -f 'type =~ histogram' "$RESULTS_DIR/${SCENARIO}.sca"; then
        SIZE=$(ls -lh "$OUTPUT_DIR/test_histograms.json" | awk '{print $5}')
        echo "   SUCCESS: test_histograms.json ($SIZE)"
    else
        echo "   FAILED"
    fi
    
    echo "4. Exporting statistics (if any)..."
    if opp_scavetool export -f JSON -o "$OUTPUT_DIR/test_statistics.json" -f 'type =~ statistic' "$RESULTS_DIR/${SCENARIO}.sca"; then
        SIZE=$(ls -lh "$OUTPUT_DIR/test_statistics.json" | awk '{print $5}')
        echo "   SUCCESS: test_statistics.json ($SIZE)"
    else
        echo "   No statistics or export failed"
    fi
    
else
    echo "ERROR: $RESULTS_DIR/${SCENARIO}.sca not found"
fi

echo ""

if [ -f "$RESULTS_DIR/${SCENARIO}.vec" ]; then
    echo "5. Exporting app vectors..."
    if opp_scavetool export -f JSON -o "$OUTPUT_DIR/test_app_vectors.json" -f 'type =~ vector AND module =~ "**.app[*]"' "$RESULTS_DIR/${SCENARIO}.vec"; then
        SIZE=$(ls -lh "$OUTPUT_DIR/test_app_vectors.json" | awk '{print $5}')
        echo "   SUCCESS: test_app_vectors.json ($SIZE)"
    else
        echo "   App filter failed, trying broader pattern..."
        if opp_scavetool export -f JSON -o "$OUTPUT_DIR/test_app_vectors.json" -f 'type =~ vector AND module =~ "*app*"' "$RESULTS_DIR/${SCENARIO}.vec"; then
            SIZE=$(ls -lh "$OUTPUT_DIR/test_app_vectors.json" | awk '{print $5}')
            echo "   SUCCESS: test_app_vectors.json ($SIZE, broad filter)"
        else
            echo "   FAILED"
        fi
    fi
else
    echo "ERROR: $RESULTS_DIR/${SCENARIO}.vec not found"
fi

echo ""
echo "Test Results:"
echo "============="
ls -la "$OUTPUT_DIR"/test_*.json 2>/dev/null

echo ""
echo "Sample data from parameters (first 10 lines):"
head -10 "$OUTPUT_DIR/test_parameters.json" 2>/dev/null

echo ""
echo "Sample data from histograms (first 10 lines):"
head -10 "$OUTPUT_DIR/test_histograms.json" 2>/dev/null
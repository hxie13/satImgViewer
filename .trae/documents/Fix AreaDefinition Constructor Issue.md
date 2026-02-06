# Fix AreaDefinition Constructor Issue

## Problem Analysis
The error occurs because the `AreaDefinition` constructor signature in pyresample has changed. The current code uses positional arguments, but the installed version expects either a different order or keyword arguments. This causes the error message indicating that 'height' and 'area_extent' are missing, even though they're being passed.

## Solution
Update the `create_target_area` function in `core/projections.py` to use a more robust approach that handles different pyresample versions.

## Implementation Steps

1. **Update AreaDefinition Constructor Call**
   - Modify the `create_target_area` function to use keyword arguments instead of positional arguments
   - This will make the code more robust across different pyresample versions
   - Ensure all required arguments are properly named

2. **Add Version Compatibility Handling**
   - Add try-except blocks to handle different constructor signatures
   - First try the newer keyword argument approach
   - Fallback to older positional argument approach if needed

3. **Test the Fix**
   - Run the application to verify the fix works
   - Ensure satellite imagery is properly projected and displayed

## Expected Outcome
- The application should successfully create `AreaDefinition` objects
- Satellite imagery should be properly resampled and displayed in the correct projection
- No more "missing required positional arguments" errors

## Files to Modify
- `core/projections.py`: Update the `create_target_area` function to use keyword arguments for the AreaDefinition constructor
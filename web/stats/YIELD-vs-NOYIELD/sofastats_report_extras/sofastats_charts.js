
makeBarChart = function(chartname, series, chartconf){
    // allow charts made without newest config items to keep working
    var gridlineWidth = ("gridlineWidth" in chartconf) ? chartconf["gridlineWidth"] : 3;
    var tooltipBorderColour = ("tooltipBorderColour" in chartconf) ? chartconf["tooltipBorderColour"] : "#ada9a5";
    var connectorStyle = ("connectorStyle" in chartconf) ? chartconf["connectorStyle"] : "defbrown";
    var outerChartBorderColour = ("outerChartBorderColour" in chartconf) ? chartconf["outerChartBorderColour"] : null;
    var innerChartBorderColour = ("innerChartBorderColour" in chartconf) ? chartconf["innerChartBorderColour"] : null;
    var outerBg = ("outerBg" in chartconf) ? chartconf["outerBg"] : null;
    var axisColour = ("axisColour" in chartconf) ? chartconf["axisColour"] : null;
    var tickColour = ("tickColour" in chartconf) ? chartconf["tickColour"] : null;
    var minorTicks = ("minorTicks" in chartconf) ? chartconf["minorTicks"] : false;
    var xTitle = ("xTitle" in chartconf) ? chartconf["xTitle"] : "";
    var axisLabelDrop = ("axisLabelDrop" in chartconf) ? chartconf["axisLabelDrop"] : 30;
    var axisLabelRotate = ("axisLabelRotate" in chartconf) ? chartconf["axisLabelRotate"] : 0;
    var leftAxisLabelShift = ("leftAxisLabelShift" in chartconf) ? chartconf["leftAxisLabelShift"] : 0;
    var yTitle = ("yTitle" in chartconf) ? chartconf["yTitle"] : "Frequency";

    /* chartwide function setting - have access to val.element (Column), val.index (0), val.run.data (y_vals), shape, x, y, chart, plot, hAxis, eventMask, type, event

    val.run has chart, group, htmlElements, dirty, stroke, fill, plot, data, dyn, name
    val.run = val.run.chart.series[0]

    val.run.chart has margins, stroke, fill, delayInMs, theme, axes, stack, plots, series, runs, dirty,coords,node,surface,dim,offsets,plotArea AND any other variables I put in with the options - the third parameter of addSeries().

    val.run.data has 0,1,2,3,4 etc such that val.run.data[0] is the y-val for the first item

*/
    var getTooltip = function(val){
        var tip = val.run.yLbls[val.index];
        return tip;
    };

    var dc = dojox.charting;
    var mychart = new dc.Chart2D(chartname, {margins: {l: 10+leftAxisLabelShift, t: 10, r: 10, b: 10+axisLabelDrop}});
    var sofa_theme = new dc.Theme({
        chart:{
	        stroke: outerChartBorderColour,
        	fill: outerBg,
	        pageStyle: null // suggested page style as an object suitable for dojo.style()
	    },
	    plotarea:{
	        stroke: innerChartBorderColour,
	        fill: chartconf["gridBg"]
	    },
	    axis:{
	        stroke:	{ // the axis itself
	            color: axisColour,
	            width: null
	        },
            tick: {	// used as a foundation for all ticks
	            color:     tickColour,
	            position:  "center",
	            fontColor: chartconf["axisLabelFontColour"]
	        },
	        majorTick:	{ // major ticks on axis, and used for major gridlines
	            width:  gridlineWidth,
	            length: 6, 
                color: chartconf["majorGridlineColour"]
	        },
	        minorTick:	{ // minor ticks on axis, and used for minor gridlines
	            width:  0.8,
	            length: 3
	        },
	        microTick:	{ // minor ticks on axis, and used for minor gridlines
	            width:  0.5,
	            length: 1
	        }
	    }
    });
    mychart.setTheme(sofa_theme);
    mychart.addAxis("x", {title: xTitle,
                    labels: chartconf["xaxisLabels"], minorTicks: minorTicks, 
                    font: "normal normal normal " + chartconf["xfontsize"] + "pt Arial",
                    rotation: axisLabelRotate
    });
    mychart.addAxis("y", {title: yTitle,
                    vertical: true, includeZero: true, 
                    max: chartconf["ymax"],
                    font: "normal normal normal 10pt Arial", fontWeight: 12
    });
    mychart.addPlot("default", {type: "ClusteredColumns", gap: chartconf["xgap"], shadows: {dx: 12, dy: 12}});
    mychart.addPlot("grid", {type: "Grid", vMajorLines: false});
    var i
    for (i in series){
        mychart.addSeries(series[i]["seriesLabel"], series[i]["yVals"], series[i]["options"]);
    }
    var anim_a = new dc.action2d.Highlight(mychart, "default", {
        highlight: chartconf["sofaHl"],
        duration: 450,
        easing:   dojo.fx.easing.sineOut
    });
    var anim_b = new dc.action2d.Shake(mychart, "default");
    var anim_c = new dc.action2d.Tooltip(mychart, "default", {text: getTooltip, 
        tooltipBorderColour: tooltipBorderColour, connectorStyle: connectorStyle});
    mychart.render();
    var legend = new dojox.charting.widget.Legend({chart: mychart, horizontal: 6}, ("legend" + chartname.substr(0,1).toUpperCase() + chartname.substr(1)));
}

makePieChart = function(chartname, slices, chartconf){
    // allow charts made without newest config items to keep working

    var pieStroke = "#8b9b98";
    var tooltipBorderColour = ("tooltipBorderColour" in chartconf) ? chartconf["tooltipBorderColour"] : "#ada9a5";
    var connectorStyle = ("connectorStyle" in chartconf) ? chartconf["connectorStyle"] : "defbrown";
    var outerChartBorderColour = ("outerChartBorderColour" in chartconf) ? chartconf["outerChartBorderColour"] : null;
    var innerChartBorderColour = ("innerChartBorderColour" in chartconf) ? chartconf["innerChartBorderColour"] : null;
    var outerBg = ("outerBg" in chartconf) ? chartconf["outerBg"] : null;
    var radius = ("radius" in chartconf) ? chartconf["radius"] : 140;
    var labelOffset = ("labelOffset" in chartconf) ? chartconf["labelOffset"] : -30;

    var dc = dojox.charting;
    var mychart = new dc.Chart2D(chartname);
        
    var sofa_theme = new dc.Theme({
		colors: chartconf["sliceColours"],
        chart: {
	        stroke: outerChartBorderColour,
        	fill: outerBg,
	        pageStyle: null // suggested page style as an object suitable for dojo.style()
	    },
		plotarea: {
			fill: chartconf["gridBg"]
		}
	});
    mychart.setTheme(sofa_theme);
    mychart.addPlot("default", {
            type: "Pie",
            font: "normal normal " + chartconf["sliceFontsize"] + "px Tahoma",
            fontColor: chartconf["labelFontColour"],
            labelOffset: labelOffset,
            radius: radius
        });

    var pieSeries = Array();
    var i;
    for (i in slices){
        pieSeries[i] = 
        {
            y: slices[i]["y"],
            text: slices[i]["text"],
            stroke: pieStroke,
            tooltip: slices[i]["tooltip"]
        }
    }
    mychart.addSeries("Series A", pieSeries);
    var anim_a = new dc.action2d.MoveSlice(mychart, "default");
    var anim_b = new dc.action2d.Highlight(mychart, "default", {
        highlight: chartconf["sofaHl"],
        duration: 450,
        easing:   dojo.fx.easing.sineOut
    });
    var anim_c = new dc.action2d.Tooltip(mychart, "default", 
                                         {tooltipBorderColour: tooltipBorderColour, connectorStyle: connectorStyle});
    mychart.render();
}

makeLineChart = function(chartname, series, chartconf){
    // allow charts made without newest config items to keep working

    var gridlineWidth = ("gridlineWidth" in chartconf) ? chartconf["gridlineWidth"] : 3;
    var tooltipBorderColour = ("tooltipBorderColour" in chartconf) ? chartconf["tooltipBorderColour"] : "#ada9a5";
    var connectorStyle = ("connectorStyle" in chartconf) ? chartconf["connectorStyle"] : "defbrown";
    var outerChartBorderColour = ("outerChartBorderColour" in chartconf) ? chartconf["outerChartBorderColour"] : null;
    var innerChartBorderColour = ("innerChartBorderColour" in chartconf) ? chartconf["innerChartBorderColour"] : null;
    var outerBg = ("outerBg" in chartconf) ? chartconf["outerBg"] : null;
    var axisColour = ("axisColour" in chartconf) ? chartconf["axisColour"] : null;
    var tickColour = ("tickColour" in chartconf) ? chartconf["tickColour"] : null;
    var minorTicks = ("minorTicks" in chartconf) ? chartconf["minorTicks"] : false;
    var microTicks = ("microTicks" in chartconf) ? chartconf["microTicks"] : false;
    var xTitle = ("xTitle" in chartconf) ? chartconf["xTitle"] : "";
    var axisLabelDrop = ("axisLabelDrop" in chartconf) ? chartconf["axisLabelDrop"] : 30;
    var axisLabelRotate = ("axisLabelRotate" in chartconf) ? chartconf["axisLabelRotate"] : 0;
    var leftAxisLabelShift = ("leftAxisLabelShift" in chartconf) ? chartconf["leftAxisLabelShift"] : 0;
    var yTitle = ("yTitle" in chartconf) ? chartconf["yTitle"] : "Frequency";

    var getTooltip = function(val){
        var tip = val.run.yLbls[val.index];
        return tip;
    };

    var dc = dojox.charting;
    var mychart = new dc.Chart2D(chartname, {margins: {l: 10+leftAxisLabelShift, t: 10, r: 10, b: 10+axisLabelDrop}});
    var sofa_theme = new dc.Theme({
        chart:{
	        stroke: outerChartBorderColour,
        	fill: null,
	        pageStyle: null // suggested page style as an object suitable for dojo.style()
	    },
	    plotarea:{
	        stroke: innerChartBorderColour,
	        fill: chartconf["gridBg"]
	    },
	    axis:{
	        stroke:	{ // the axis itself
	            color: axisColour,
	            width: null
	        },
            tick: {	// used as a foundation for all ticks
	            color:     tickColour,
	            position:  "center",
	            fontColor: chartconf["axisLabelFontColour"]
	        },
	        majorTick:	{ // major ticks on axis, and used for major gridlines
	            width:  gridlineWidth,
	            length: 6, 
                color: chartconf["majorGridlineColour"]
	        },
	        minorTick:	{ // minor ticks on axis, and used for minor gridlines
	            width:  2,
	            length: 4,
                color: chartconf["majorGridlineColour"]
	        },
	        microTick:	{ // minor ticks on axis, and used for minor gridlines
	            width:  1.7,
	            length: 3,
                color: tickColour
	        }
	    }
    });
    mychart.setTheme(sofa_theme);
    mychart.addAxis("x", {title: xTitle,
                    labels: chartconf["xaxisLabels"], minorTicks: minorTicks, microTicks: microTicks, minorLabels: minorTicks,
                    font: "normal normal normal " + chartconf["xfontsize"] + "pt Arial",
                    rotation: axisLabelRotate
    });
    mychart.addAxis("y", {title: yTitle,
                    vertical: true, includeZero: true, 
                    max: chartconf["ymax"],
                    font: "normal normal normal 10pt Arial", fontWeight: 12
    });
    mychart.addPlot("default", {type: "Lines", markers: true, shadows: {dx: 2, dy: 2, dw: 2}});
    mychart.addPlot("grid", {type: "Grid", vMajorLines: false});
    var i
    for (i in series){
        mychart.addSeries(series[i]["seriesLabel"], series[i]["yVals"], series[i]["options"]);
    }
    var anim_a = new dc.action2d.Magnify(mychart, "default");
    var anim_b = new dc.action2d.Tooltip(mychart, "default", {text: getTooltip, 
        tooltipBorderColour: tooltipBorderColour, connectorStyle: connectorStyle});
    mychart.render();
    var legend = new dojox.charting.widget.Legend({chart: mychart}, ("legend" + chartname.substr(0,1).toUpperCase() + chartname.substr(1)));
}

makeAreaChart = function(chartname, series, chartconf){
    // allow charts made without newest config items to keep working
    var gridlineWidth = ("gridlineWidth" in chartconf) ? chartconf["gridlineWidth"] : 3;
    var tooltipBorderColour = ("tooltipBorderColour" in chartconf) ? chartconf["tooltipBorderColour"] : "#ada9a5";
    var connectorStyle = ("connectorStyle" in chartconf) ? chartconf["connectorStyle"] : "defbrown";
    var outerChartBorderColour = ("outerChartBorderColour" in chartconf) ? chartconf["outerChartBorderColour"] : null;
    var innerChartBorderColour = ("innerChartBorderColour" in chartconf) ? chartconf["innerChartBorderColour"] : null;
    var outerBg = ("outerBg" in chartconf) ? chartconf["outerBg"] : null;
    var axisColour = ("axisColour" in chartconf) ? chartconf["axisColour"] : null;
    var tickColour = ("tickColour" in chartconf) ? chartconf["tickColour"] : "black";
    var minorTicks = ("minorTicks" in chartconf) ? chartconf["minorTicks"] : false;
    var microTicks = ("microTicks" in chartconf) ? chartconf["microTicks"] : false;
    var xTitle = ("xTitle" in chartconf) ? chartconf["xTitle"] : "Category";
    var yTitle = ("yTitle" in chartconf) ? chartconf["yTitle"] : "Frequency";
    var leftAxisLabelShift = ("leftAxisLabelShift" in chartconf) ? chartconf["leftAxisLabelShift"] : 0;
    var axisLabelDrop = ("axisLabelDrop" in chartconf) ? chartconf["axisLabelDrop"] : 30;
    var axisLabelRotate = ("axisLabelRotate" in chartconf) ? chartconf["axisLabelRotate"] : 0;

    var getTooltip = function(val){
        var tip = val.run.yLbls[val.index];
        return tip;
    };

    var dc = dojox.charting;
    var mychart = new dc.Chart2D(chartname, {margins: {l: 10+leftAxisLabelShift, t: 10, r: 10, b: 10+axisLabelDrop}});
    var sofa_theme = new dc.Theme({
        chart:{
	        stroke: outerChartBorderColour,
        	fill: null,
	        pageStyle: null // suggested page style as an object suitable for dojo.style()
	    },
	    plotarea:{
	        stroke: innerChartBorderColour,
	        fill: chartconf["gridBg"]
	    },
	    axis:{
	        stroke:	{ // the axis itself
	            color: axisColour,
	            width: null
	        },
            tick: {	// used as a foundation for all ticks
	            color:     tickColour,
	            position:  "center",
	            fontColor: chartconf["axisLabelFontColour"]
	        },
	        majorTick:	{ // major ticks on axis, and used for major gridlines
	            width:  gridlineWidth,
	            length: 6, 
                color: chartconf["majorGridlineColour"]
	        },
	        minorTick:	{ // minor ticks on axis, and used for minor gridlines
	            width:  2,
	            length: 4,
                color: chartconf["majorGridlineColour"]
	        },
	        microTick:	{ // minor ticks on axis, and used for minor gridlines
	            width:  1.7,
	            length: 3,
                color: tickColour
	        }
	    }
    });
    mychart.setTheme(sofa_theme);
    mychart.addAxis("x", {title: xTitle,
                    labels: chartconf["xaxisLabels"], minorTicks: minorTicks,  microTicks: microTicks, minorLabels: minorTicks,
                    font: "normal normal normal " + chartconf["xfontsize"] + "pt Arial",
                    rotation: axisLabelRotate
    });
    mychart.addAxis("y", {title: yTitle,  // normal normal bold
                    vertical: true, includeZero: true, 
                    max: chartconf["ymax"], 
                    font: "normal normal normal 10pt Arial", fontWeight: 12
    });
    mychart.addPlot("default", {type: "Areas", lines: true, areas: true, markers: true});
    mychart.addPlot("grid", {type: "Grid", vMajorLines: false});
    var i
    for (i in series){
        mychart.addSeries(series[i]["seriesLabel"], series[i]["yVals"], series[i]["options"]);
    }
    var anim_a = new dc.action2d.Magnify(mychart, "default");
    var anim_b = new dc.action2d.Tooltip(mychart, "default", {text: getTooltip, 
        tooltipBorderColour: tooltipBorderColour, connectorStyle: connectorStyle});
    mychart.render();
    var legend = new dojox.charting.widget.Legend({chart: mychart}, ("legend" + chartname.substr(0,1).toUpperCase() + chartname.substr(1)));
}

makeHistogram = function(chartname, datadets, chartconf){
    // allow charts made without newest config items to keep working
    var gridlineWidth = ("gridlineWidth" in chartconf) ? chartconf["gridlineWidth"] : 3;
    var tooltipBorderColour = ("tooltipBorderColour" in chartconf) ? chartconf["tooltipBorderColour"] : "#ada9a5";
    var outerChartBorderColour = ("outerChartBorderColour" in chartconf) ? chartconf["outerChartBorderColour"] : null;
    var innerChartBorderColour = ("innerChartBorderColour" in chartconf) ? chartconf["innerChartBorderColour"] : null;
    var outerBg = ("outerBg" in chartconf) ? chartconf["outerBg"] : null;
    var axisColour = ("axisColour" in chartconf) ? chartconf["axisColour"] : null;
    var tickColour = ("tickColour" in chartconf) ? chartconf["tickColour"] : null;
    var minorTicks = ("minorTicks" in chartconf) ? chartconf["minorTicks"] : false;
    var yTitle = ("yTitle" in chartconf) ? chartconf["yTitle"] : "P";
    var connectorStyle = ("connectorStyle" in chartconf) ? chartconf["connectorStyle"] : "defbrown";
    var leftAxisLabelShift = ("leftAxisLabelShift" in chartconf) ? chartconf["leftAxisLabelShift"] : 0;
    var incNormal = ("incNormal" in chartconf)? chartconf["incNormal"] : false;

    // chartwide function setting - have access to val.element (Column), val.index (0), val.run.data (y_vals)
    var getTooltip = function(val){
        return "Values: " + datadets["binLabels"][val.index] + "<br>" + yTitle + ": " + val.y;
    };

    var dc = dojox.charting;
    var mychart = new dc.Chart2D(chartname, {margins: {l: 10+leftAxisLabelShift, t: 10, r: 10, b: 10}});
    var sofa_theme = new dc.Theme({
        chart:{
	        stroke: outerChartBorderColour,
        	fill: outerBg,
	        pageStyle: null // suggested page style as an object suitable for dojo.style()
	    },
	    plotarea:{
	        stroke: innerChartBorderColour,
	        fill: chartconf["gridBg"]
	    },
	    axis:{
	        stroke:	{ // the axis itself
	            color: axisColour,
	            width: null
	        },
            tick: {	// used as a foundation for all ticks
	            color:     tickColour,
	            position:  "center",
	            fontColor: chartconf["axisLabelFontColour"]
	        },
	        majorTick:	{ // major ticks on axis, and used for major gridlines
	            width:  gridlineWidth,
	            length: 6, 
                color: chartconf["majorGridlineColour"]
	        },
	        minorTick:	{ // minor ticks on axis, and used for minor gridlines
	            width:  0.8,
	            length: 3
	        },
	        microTick:	{ // minor ticks on axis, and used for minor gridlines
	            width:  0.5,
	            length: 1
	        }
	    }
    });
    mychart.setTheme(sofa_theme);
    mychart.addAxis("x", {title: datadets["seriesLabel"],
                    labels: chartconf["xaxisLabels"], minorTicks: false, microTicks: false,
                    font: "normal normal normal " + chartconf["xfontsize"] + "pt Arial"
    });
    mychart.addAxis("x2", {min: chartconf["minVal"], max: chartconf["maxVal"],
                    minorTicks: minorTicks, 
                    font: "normal normal normal " + chartconf["xfontsize"] + "pt Arial"
    });
    mychart.addAxis("y", {title: yTitle,  // normal normal bold
                    vertical: true, includeZero: true, font: "normal normal normal 10pt Arial", fontWeight: 12
    });
    mychart.addPlot("normal", {type: "Lines", markers: true, shadows: {dx: 2, dy: 2, dw: 2}}); // must come first to be seen!
    mychart.addPlot("default", {type: "Columns", gap: 0, shadows: {dx: 12, dy: 12}});
    mychart.addPlot("grid", {type: "Grid", vMajorLines: false});
    mychart.addPlot("othergrid", {type: "Areas", hAxis: "x2", vAxis: "y"});
    mychart.addSeries(datadets["seriesLabel"], datadets["yVals"], datadets["style"]);
    if(incNormal == true){
        mychart.addPlot("normal", {type: "Lines", markers: false, shadows: {dx: 2, dy: 2, dw: 2}});
        mychart.addSeries("Normal Dist Curve", datadets["normYs"], datadets["normStyle"]); 
    }
    var anim_a = new dc.action2d.Highlight(mychart, "default", {
        highlight: chartconf["sofaHl"],
        duration: 450,
        easing:   dojo.fx.easing.sineOut
    });
    var anim_b = new dc.action2d.Shake(mychart, "default");
    var anim_c = new dc.action2d.Tooltip(mychart, "default", {text: getTooltip, 
        tooltipBorderColour: tooltipBorderColour, connectorStyle: connectorStyle});
    mychart.render();
}

makeScatterplot = function(chartname, series, chartconf){

    // allow charts made without newest config items to keep working
    var gridlineWidth = ("gridlineWidth" in chartconf) ? chartconf["gridlineWidth"] : 3;
    var tooltipBorderColour = ("tooltipBorderColour" in chartconf) ? chartconf["tooltipBorderColour"] : "#ada9a5";
    var outerChartBorderColour = ("outerChartBorderColour" in chartconf) ? chartconf["outerChartBorderColour"] : null;
    var innerChartBorderColour = ("innerChartBorderColour" in chartconf) ? chartconf["innerChartBorderColour"] : null;
    var outerBg = ("outerBg" in chartconf) ? chartconf["outerBg"] : null;
    var axisColour = ("axisColour" in chartconf) ? chartconf["axisColour"] : null;
    var tickColour = ("tickColour" in chartconf) ? chartconf["tickColour"] : null;
    var minorTicks = ("minorTicks" in chartconf) ? chartconf["minorTicks"] : false;
    var xTitle = ("xTitle" in chartconf) ? chartconf["xTitle"] : "Variable A";
    var axisLabelDrop = ("axisLabelDrop" in chartconf) ? chartconf["axisLabelDrop"] : 0;
    var leftAxisLabelShift = ("leftAxisLabelShift" in chartconf) ? chartconf["leftAxisLabelShift"] : 0;
    var yTitle = ("yTitle" in chartconf) ? chartconf["yTitle"] : "Variable B";
    var connectorStyle = ("connectorStyle" in chartconf) ? chartconf["connectorStyle"] : "defbrown";

    // chartwide function setting - have access to val.element (Column), val.index (0), val.run.data (y_vals)
    var getTooltip = function(val){
        return "(x: " + val.x + ", y: " + val.y + ")";
    };

    var dc = dojox.charting;
    var mychart = new dc.Chart2D(chartname, {margins: {l: 10+leftAxisLabelShift, t: 10, r: 10, b: 10+axisLabelDrop}});
    var sofa_theme = new dc.Theme({
        chart:{
	        stroke: outerChartBorderColour,
        	fill: outerBg,
	        pageStyle: null // suggested page style as an object suitable for dojo.style()
	    },
	    plotarea:{
	        stroke: innerChartBorderColour,
	        fill: chartconf["gridBg"]
	    },
	    axis:{
	        stroke:	{ // the axis itself
	            color: axisColour,
	            width: null
	        },
            tick: {	// used as a foundation for all ticks
	            color:     tickColour,
	            position:  "center",
	            fontColor: chartconf["axisLabelFontColour"]
	        },
	        majorTick:	{ // major ticks on axis, and used for major gridlines
	            width:  gridlineWidth,
	            length: 6, 
                color: chartconf["majorGridlineColour"]
	        },
	        minorTick:	{ // minor ticks on axis, and used for minor gridlines
	            width:  0.8,
	            length: 3
	        },
	        microTick:	{ // minor ticks on axis, and used for minor gridlines
	            width:  0.5,
	            length: 1
	        }
	    }
    });
    mychart.setTheme(sofa_theme);
    mychart.addAxis("x", {title: xTitle,
                    min: chartconf["xmin"], max: chartconf["xmax"],
                    minorTicks: minorTicks, microTicks: false,
                    font: "normal normal normal " + chartconf["xfontsize"] + "pt Arial"
    });
    mychart.addAxis("y", {title: yTitle,
                    min: chartconf["ymin"], max: chartconf["ymax"],
                    vertical: true, font: "normal normal normal 10pt Arial", fontWeight: 12
    });
    mychart.addPlot("default", {type: "Scatter"});
    mychart.addPlot("grid", {type: "Grid", vMajorLines: true});
    var i
    for (i in series){
        mychart.addSeries(series[i]["seriesLabel"], series[i]["xyPairs"], series[i]["style"]);
    }
    var anim_a = new dc.action2d.Magnify(mychart, "default");
    var anim_b = new dc.action2d.Tooltip(mychart, "default", {text: getTooltip, 
        tooltipBorderColour: tooltipBorderColour, connectorStyle: connectorStyle});
    mychart.render();
    var legend = new dojox.charting.widget.Legend({chart: mychart}, ("legend" + chartname.substr(0,1).toUpperCase() + chartname.substr(1)));
    var anim_a = new dc.action2d.Highlight(mychart, "default", {
        highlight: chartconf["sofaHl"],
        duration: 450,
        easing:   dojo.fx.easing.sineOut
    });
    var anim_b = new dc.action2d.Shake(mychart, "default");
    var anim_c = new dc.action2d.Tooltip(mychart, "default", {text: getTooltip, 
        tooltipBorderColour: tooltipBorderColour, connectorStyle: connectorStyle});
    mychart.render();
}

makeBoxAndWhisker = function(chartname, series, seriesconf, chartconf){
    // allow charts made without newest config items to keep working
    var gridlineWidth = ("gridlineWidth" in chartconf) ? chartconf["gridlineWidth"] : 3;
    var tooltipBorderColour = ("tooltipBorderColour" in chartconf) ? chartconf["tooltipBorderColour"] : "#ada9a5";
    var connectorStyle = ("connectorStyle" in chartconf) ? chartconf["connectorStyle"] : "defbrown";
    var outerChartBorderColour = ("outerChartBorderColour" in chartconf) ? chartconf["outerChartBorderColour"] : null;
    var innerChartBorderColour = ("innerChartBorderColour" in chartconf) ? chartconf["innerChartBorderColour"] : null;
    var majorGridlineColour = ("majorGridlineColour" in chartconf) ? chartconf["majorGridlineColour"] : null;
    var axisLabelFontColour = ("axisLabelFontColour" in chartconf) ? chartconf["axisLabelFontColour"] : null;
    var outerBg = ("outerBg" in chartconf) ? chartconf["outerBg"] : null;
    var axisColour = ("axisColour" in chartconf) ? chartconf["axisColour"] : null;
    var tickColour = ("tickColour" in chartconf) ? chartconf["tickColour"] : null;
    var minorTicks = ("minorTicks" in chartconf) ? chartconf["minorTicks"] : false;
    var xTitle = ("xTitle" in chartconf) ? chartconf["xTitle"] : "";
    var axisLabelDrop = ("axisLabelDrop" in chartconf) ? chartconf["axisLabelDrop"] : 30;
    var axisLabelRotate = ("axisLabelRotate" in chartconf) ? chartconf["axisLabelRotate"] : 0;
    var leftAxisLabelShift = ("leftAxisLabelShift" in chartconf) ? chartconf["leftAxisLabelShift"] : 0;
    var yTitle = ("yTitle" in chartconf) ? chartconf["yTitle"] : "Frequency";

    // chartwide function setting - have access to val.element (Column), val.index (0), val.run.data (y_vals)
    var getTooltip = function(val){
        return val.y;
    };

    var dc = dojox.charting;
    var mychart = new dc.Chart2D(chartname, {margins: {l: 10+leftAxisLabelShift, t: 10, r: 10, b: 10+axisLabelDrop}});

    var sofa_theme = new dc.Theme({
        chart:{
	        stroke:    outerChartBorderColour,
        	fill:      outerBg,
	        pageStyle: null // suggested page style as an object suitable for dojo.style()
	    },
	    plotarea:{
	        stroke: innerChartBorderColour,
	        fill:   chartconf["gridBg"]
	    },
	    axis:{
	        stroke:	{ // the axis itself
	            color: axisColour,
	            width: null
	        },
            tick: {	// used as a foundation for all ticks
	            color:     tickColour,
	            position:  "center",
	            fontColor: axisLabelFontColour
	        },
	        majorTick:	{ // major ticks on axis, and used for major gridlines
	            width:  gridlineWidth,
	            length: 6, 
                color:  tickColour // we have vMajorLines off so we don't need to match grid color e.g. null
	        },
	        minorTick:	{ // minor ticks on axis, and used for minor gridlines
	            width:  0.8,
	            length: 3
	        },
	        microTick:	{ // minor ticks on axis, and used for minor gridlines
	            width:  0.5,
	            length: 1
	        }
	    }
    });
    mychart.setTheme(sofa_theme);
    mychart.addPlot("default", {type: "Boxplot", markers: true});
    mychart.addPlot("grid", {type: "Grid", vMajorLines: false});
    mychart.addAxis("x", {title: xTitle, min: chartconf["xmin"], max: chartconf["xmax"], 
                          majorTicks: true, minorTicks: minorTicks, 
                          labels: chartconf["xaxisLabels"],
                          font: "normal normal normal " + chartconf["xfontsize"] + "pt Arial",
                          rotation: axisLabelRotate});
    mychart.addAxis("y", {title: yTitle, vertical: true, min: chartconf["ymin"], max: chartconf["ymax"], 
                          majorTicks: true, minorTicks: true,
                          font: "normal normal normal " + chartconf["yfontsize"] + "pt Arial"});
    var i
    for (i in series){
        mychart.addSeries(series[i]["seriesLabel"], [], series[i]["boxDets"]);
    }
    var anim_a = new dc.action2d.Highlight(mychart, "default", {
        highlight: chartconf["makefaint"],
        duration: 450,
        easing:   dojo.fx.easing.sineOut
    });
    var anim_b = new dc.action2d.Tooltip(mychart, "default", 
                                         {text: getTooltip, tooltipBorderColour: tooltipBorderColour, 
                                          connectorStyle: connectorStyle});
    mychart.render();

    var dummychart = new dc.Chart2D("dum" + chartname);
    dummychart.addPlot("default", {type: "ClusteredColumns"});
    for (i in seriesconf){
        dummychart.addSeries(seriesconf[i]["seriesLabel"], [1,2], seriesconf[i]["seriesStyle"]);
    }
    dummychart.render();
    var legend = new dojox.charting.widget.Legend({chart: dummychart}, ("legend" + chartname.substr(0,1).toUpperCase() + chartname.substr(1)));

}
